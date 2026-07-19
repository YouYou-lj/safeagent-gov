"""SkillScan-Gov upload and scan routes."""

import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.auth import require_roles
from safeagent_gov.audit import create_trace, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.supply_chain import scan_skill_package

router = APIRouter(prefix="/api/skill", tags=["SkillScan-Gov"])
ALLOWED_SUFFIXES = {".zip", ".py", ".js", ".ts", ".md", ".yaml", ".yml", ".json", ".txt", ".sh"}
MAX_BYTES = 10 * 1024 * 1024


@router.post("/scan")
async def scan_skill(
    file: UploadFile = File(...),
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "reviewer")),
):
    suffix = Path(file.filename or "upload").suffix.casefold()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="不支持的文件类型")
    trace_id = create_trace(
        f"扫描 Skill：{file.filename}",
        "skill_upload",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="skillscan-api",
    )
    temp_dir = Path(tempfile.mkdtemp(prefix="safeagent-upload-"))
    target = temp_dir / f"package{suffix}"
    try:
        size = 0
        with target.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(status_code=413, detail="上传文件超过 10 MB")
                handle.write(chunk)
        result = scan_skill_package(str(target))
        log_event(trace_id, "skill_scan", {"filename": file.filename, **result})
        log_event(trace_id, "final_output", {"status": "scan_complete", "output": result["recommendation"]})
        return {"trace_id": trace_id, **result}
    except (ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
