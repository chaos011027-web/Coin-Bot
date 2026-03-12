import os
import sys
import time
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional


LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - RetrainPipeline - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "retrain_pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("RetrainPipeline")


class RetrainPipeline:
    """
    夜间自动训练管线（最小可用版）

    目标：
    1) 不改你现有主程序
    2) 不强依赖 midnight_hunter.py / train_model.py 的内部函数签名
    3) 直接作为独立脚本调度执行
    """

    def __init__(
        self,
        python_executable: Optional[str] = None,
        midnight_script: str = "midnight_hunter.py",
        train_script: str = "train_model.py",
        state_file: str = "data/retrain_pipeline_state.json",
        model_path: str = "models/meme_strategy_v1.txt",
    ):
        self.python_executable = python_executable or sys.executable
        self.midnight_script = Path(midnight_script)
        self.train_script = Path(train_script)
        self.state_file = Path(state_file)
        self.model_path = Path(model_path)

        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

    # =========================
    # state helpers
    # =========================
    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取状态文件失败，已忽略: {e}")
            return {}

    def _save_state(self, payload: Dict[str, Any]) -> None:
        tmp_path = self.state_file.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.state_file)

    # =========================
    # subprocess helpers
    # =========================
    def _run_script(self, script_path: Path, stage_name: str) -> Dict[str, Any]:
        if not script_path.exists():
            msg = f"{stage_name} 脚本不存在: {script_path}"
            logger.error(msg)
            return {
                "ok": False,
                "stage": stage_name,
                "returncode": -1,
                "stdout": "",
                "stderr": msg,
                "duration_sec": 0.0,
            }

        logger.info(f"🚀 开始执行 {stage_name}: {script_path}")
        start_ts = time.time()

        try:
            proc = subprocess.run(
                [self.python_executable, str(script_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            duration = time.time() - start_ts

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""

            if proc.returncode == 0:
                logger.info(f"✅ {stage_name} 执行成功，用时 {duration:.2f}s")
            else:
                logger.error(f"❌ {stage_name} 执行失败，returncode={proc.returncode}，用时 {duration:.2f}s")

            if stdout.strip():
                logger.info(f"[{stage_name} STDOUT]\n{stdout[-5000:]}")
            if stderr.strip():
                logger.warning(f"[{stage_name} STDERR]\n{stderr[-5000:]}")

            return {
                "ok": proc.returncode == 0,
                "stage": stage_name,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_sec": round(duration, 3),
            }

        except Exception as e:
            duration = time.time() - start_ts
            logger.exception(f"💥 {stage_name} 执行异常: {e}")
            return {
                "ok": False,
                "stage": stage_name,
                "returncode": -2,
                "stdout": "",
                "stderr": str(e),
                "duration_sec": round(duration, 3),
            }

    # =========================
    # pipeline
    # =========================
    def run(self) -> Dict[str, Any]:
        """
        执行顺序：
        1. 先跑 midnight_hunter.py 做打标/导出
        2. 再跑 train_model.py 做训练
        3. 检查模型文件是否生成
        """
        started_at = time.time()
        state_before = self._load_state()

        result: Dict[str, Any] = {
            "started_at": started_at,
            "started_at_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)),
            "python_executable": self.python_executable,
            "midnight_script": str(self.midnight_script),
            "train_script": str(self.train_script),
            "previous_state": state_before,
        }

        midnight_res = self._run_script(self.midnight_script, "MidnightHunter")
        result["midnight_hunter"] = midnight_res

        if not midnight_res["ok"]:
            result["ok"] = False
            result["finished_at"] = time.time()
            result["finished_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(result["finished_at"]))
            result["reason"] = "midnight_hunter 执行失败，训练中止"
            self._save_state(result)
            return result

        train_res = self._run_script(self.train_script, "TrainModel")
        result["train_model"] = train_res

        model_exists = self.model_path.exists()
        model_mtime = self.model_path.stat().st_mtime if model_exists else None

        result["model_check"] = {
            "model_path": str(self.model_path),
            "exists": model_exists,
            "mtime": model_mtime,
            "mtime_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(model_mtime)) if model_mtime else None,
        }

        result["ok"] = bool(train_res["ok"] and model_exists)
        result["finished_at"] = time.time()
        result["finished_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(result["finished_at"]))
        result["duration_sec"] = round(result["finished_at"] - started_at, 3)

        if result["ok"]:
            result["reason"] = "训练管线执行完成，模型文件已就绪"
            logger.info("🎯 训练闭环完成：模型文件已生成/更新")
        else:
            if not train_res["ok"]:
                result["reason"] = "train_model 执行失败"
            elif not model_exists:
                result["reason"] = "训练脚本执行结束，但模型文件不存在"
            logger.error(f"⚠️ 训练闭环未完成: {result['reason']}")

        self._save_state(result)
        return result


def main():
    pipeline = RetrainPipeline()
    result = pipeline.run()

    print("\n" + "=" * 80)
    print("Retrain Pipeline Result")
    print("=" * 80)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()