def report_progress(progress_queue, stage, current, total, unit="tile"):
    if progress_queue is None:
        return

    total = max(0, int(total))
    current = max(0, min(int(current), total))
    percent = round(current * 100 / total) if total else 0
    progress_queue.put(
        {
            "stage": stage,
            "current": current,
            "total": total,
            "unit": unit,
            "percent": percent,
        }
    )
