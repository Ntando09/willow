"""Willow v10.4 — Self-repair brain with EXA fallback and A/B testing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from exa_py import Exa

ROOT = Path(__file__).resolve().parent
BACKUP_DIR = ROOT / "backups"
REPAIR_LOG = BACKUP_DIR / "self_repair.log"

load_dotenv(ROOT / ".env")

EXA_API_KEY = os.getenv("EXA_API_KEY", "")


class WillowBrain:
    """Self-improving Willow brain — auto-fix, search, A/B test, escalate to human."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ROOT
        self.backup_dir = self.root / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.exa = Exa(api_key=EXA_API_KEY) if EXA_API_KEY else None
        self._log("WillowBrain v10.4 initialized")

    def _log(self, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{ts}] {message}"
        print(line)
        with REPAIR_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def backup_file(self, filepath: Path) -> Path:
        """Backup a file before modification."""
        if not filepath.exists():
            raise FileNotFoundError(f"Cannot backup missing file: {filepath}")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rel = filepath.relative_to(self.root) if filepath.is_relative_to(self.root) else filepath.name
        dest = self.backup_dir / f"{rel.as_posix().replace('/', '_')}_{ts}.bak"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(filepath, dest)
        self._log(f"Backed up {filepath} -> {dest}")
        return dest

    def _attempt_fix(self, error: str, attempt: int) -> str:
        """Generate a fix strategy based on error type."""
        err_lower = error.lower()
        if "modulenotfounderror" in err_lower or "no module named" in err_lower:
            mod = error.split("'")[1] if "'" in error else "unknown"
            return f"pip install {mod}"
        if "permission" in err_lower or "access is denied" in err_lower:
            return "permission_issue"
        if "syntaxerror" in err_lower:
            return "review_syntax_and_indentation"
        if attempt == 1:
            return "retry_with_clean_imports"
        return "rollback_and_retry"

    def _apply_fix(self, fix: str, context: dict[str, Any]) -> bool:
        """Try to apply an automated fix. Returns True if fix was applied."""
        if fix == "permission_issue":
            return False
        if fix.startswith("pip install"):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", fix.replace("pip install ", "")],
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=str(self.root),
                )
                self._log(f"Applied fix: {fix}")
                return True
            except subprocess.CalledProcessError as exc:
                self._log(f"Fix failed: {exc.stderr}")
                return False
        if fix == "rollback_and_retry":
            backup = context.get("backup_path")
            target = context.get("target_path")
            if backup and target and Path(backup).exists():
                shutil.copy2(backup, target)
                self._log(f"Rolled back {target} from {backup}")
                return True
        if fix == "retry_with_clean_imports":
            self._log("Retry with clean imports (no file change)")
            return True
        if fix == "review_syntax_and_indentation":
            self._log("Syntax fix requires manual review")
            return False
        return False

    def _search_web_fix(self, error: str) -> list[str]:
        """Search EXA for fix suggestions."""
        if not self.exa:
            self._log("EXA not configured — skipping web search")
            return []
        query = f"fix {error} python"
        self._log(f"Searching EXA: {query}")
        try:
            result = self.exa.search(query, num_results=3, use_autoprompt=True)
            suggestions = []
            for r in result.results:
                text = (getattr(r, "text", None) or getattr(r, "snippet", None) or "")[:300]
                suggestions.append(f"{getattr(r, 'title', 'Result')}: {text}")
            return suggestions
        except Exception as exc:
            self._log(f"EXA search failed: {exc}")
            return []

    def _ab_test(
        self,
        old_fn: Callable[[], Any],
        new_fn: Callable[[], Any],
    ) -> tuple[bool, str]:
        """Run old vs new; prefer new only if it succeeds and old fails or new is better."""
        old_ok, old_err = True, ""
        new_ok, new_err = True, ""

        try:
            old_fn()
        except Exception as exc:
            old_ok = False
            old_err = str(exc)

        try:
            new_fn()
        except Exception as exc:
            new_ok = False
            new_err = str(exc)

        if new_ok and not old_ok:
            return True, "New version works; old failed."
        if new_ok and old_ok:
            return True, "Both pass; keeping new."
        if not new_ok and old_ok:
            return False, f"New failed ({new_err}); reverting to old."
        return False, f"Both failed. Old: {old_err}. New: {new_err}."

    def _is_human_required(self, error: str, fixes_tried: list[str], search_results: list[str]) -> tuple[bool, str, list[str]]:
        """Detect if human intervention is required."""
        err_lower = error.lower()
        human_steps: list[str] = []

        if any(k in err_lower for k in ("permission", "access is denied", "administrator")):
            reason = "This requires elevated permissions I cannot obtain."
            human_steps = [
                "Run terminal as Administrator",
                "Grant Will write access to the target directory",
                "Tell Will 'try again' when permissions are fixed",
            ]
            return True, reason, human_steps

        if any(k in err_lower for k in ("hardware", "device not found", "camera", "microphone")):
            reason = "This requires physical hardware or driver setup."
            human_steps = [
                "Check that the device is connected and enabled",
                "Install or update the device driver",
                "Tell Will 'try again' when hardware is ready",
            ]
            return True, reason, human_steps

        if not search_results and all(f in ("permission_issue", "review_syntax_and_indentation") for f in fixes_tried):
            reason = "Automated fixes exhausted and no web solutions found."
            human_steps = [
                "Review the error in backups/self_repair.log",
                "Apply the fix manually based on the error",
                "Tell Will 'try again' when done",
            ]
            return True, reason, human_steps

        return False, "", []

    def add_feature(
        self,
        feature_name: str,
        target_path: Path,
        apply_fn: Callable[[], None],
        verify_fn: Callable[[], None],
        old_verify_fn: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """
        Attempt to add a feature with self-repair:
        1. Backup target
        2. Apply change
        3. On failure: auto-fix 2x, EXA search, A/B test
        4. Escalate to human if impossible
        """
        self._log(f"Adding feature: {feature_name}")
        backup_path: Path | None = None
        fixes_tried: list[str] = []
        search_results: list[str] = []
        last_error = ""

        try:
            if target_path.exists():
                backup_path = self.backup_file(target_path)

            apply_fn()
            verify_fn()
            self._log(f"Feature '{feature_name}' added successfully")
            return {"success": True, "feature": feature_name}

        except Exception as exc:
            last_error = str(exc)
            self._log(f"Feature '{feature_name}' failed: {last_error}")
            self._log(traceback.format_exc())

        context: dict[str, Any] = {
            "backup_path": str(backup_path) if backup_path else None,
            "target_path": str(target_path),
        }

        for attempt in range(1, 3):
            fix = self._attempt_fix(last_error, attempt)
            fixes_tried.append(fix)
            self._log(f"Auto-fix attempt {attempt}: {fix}")

            if fix == "permission_issue":
                break

            if self._apply_fix(fix, context):
                try:
                    verify_fn()
                    self._log(f"Feature '{feature_name}' fixed on attempt {attempt}")
                    return {"success": True, "feature": feature_name, "fix": fix}
                except Exception as exc:
                    last_error = str(exc)
                    self._log(f"Verify still failing after fix {attempt}: {last_error}")

        search_results = self._search_web_fix(last_error)
        if search_results:
            self._log(f"EXA suggestions: {json.dumps(search_results[:2])}")

        if old_verify_fn and backup_path:
            def old_test() -> None:
                shutil.copy2(backup_path, target_path)
                old_verify_fn()

            def new_test() -> None:
                apply_fn()
                verify_fn()

            passed, ab_msg = self._ab_test(old_test, new_test)
            self._log(f"A/B test: {ab_msg}")
            if passed:
                return {"success": True, "feature": feature_name, "ab_test": ab_msg}
            if backup_path.exists():
                shutil.copy2(backup_path, target_path)
                self._log("Reverted to backup after failed A/B test")

        human_needed, reason, steps = self._is_human_required(last_error, fixes_tried, search_results)
        if human_needed:
            msg = self._format_human_message(
                feature_name, last_error, fixes_tried, f"fix {last_error} python", reason, steps
            )
            self._log(msg)
            return {"success": False, "message": msg}

        msg = self._format_human_message(
            feature_name,
            last_error,
            fixes_tried,
            f"fix {last_error} python",
            "All automated recovery paths exhausted.",
            [
                "Check backups/self_repair.log for details",
                "Fix the underlying issue manually",
                "Tell Will 'try again' when done",
            ],
        )
        self._log(msg)
        return {"success": False, "message": msg}

    @staticmethod
    def _format_human_message(
        feature: str,
        error: str,
        fixes: list[str],
        query: str,
        reason: str,
        steps: list[str],
    ) -> str:
        fix_str = ", ".join(fixes[:2]) if fixes else "none"
        step_lines = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
        return (
            f"Sir, I tried to add {feature}, broke with {error}. "
            f"I tried {fix_str} and searched for {query}. "
            f"I can't because {reason}. "
            f"Human steps needed:\n{step_lines}\n"
            f"Tell me 'try again' when done."
        )


if __name__ == "__main__":
    brain = WillowBrain()
    print("WillowBrain v10.4 ready.")
    print(f"Backups: {BACKUP_DIR}")
    print(f"Log: {REPAIR_LOG}")
