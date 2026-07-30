from app.models import BackgroundJob


def job_submission_response(job: BackgroundJob) -> dict:
    """Compatible job response: legacy columns plus the v1 submission contract."""
    result = {column.key: getattr(job, column.key) for column in job.__table__.columns}
    deduplicated = bool(getattr(job, "submission_deduplicated", False))
    result.update({
        "job_id": job.id,
        "deduplicated": deduplicated,
        "message": "相同任务已存在，已返回当前任务" if deduplicated else "任务已提交",
        "status_url": f"/api/jobs/{job.id}",
    })
    return result
