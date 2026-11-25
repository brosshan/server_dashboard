import asyncio
import logging
from .database import Database
from .prober import check_device_health
from .notifier import broadcast

logger = logging.getLogger("prober_scheduler")


async def run_device_probes(database: Database):
    """
    定時掃描所有啟用的自定義設備並更新狀態，並透過 WebSocket 廣播
    """
    while True:
        try:
            devices = await database.list_devices()
            active_devices = [d for d in devices if d.get("is_active")]
            
            # 並行檢測以提升速度
            tasks = [check_device_health(d) for d in active_devices]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            updated_devices = []
            for d, res in zip(active_devices, results):
                if isinstance(res, dict):
                    status = res["status"]
                    latency = res["latency_ms"]
                    detail = res["status_detail"]
                    snmp_data = res.get("snmp")
                    await database.update_device_status(d["id"], status, latency, detail, snmp_data)
                    d["status"] = status
                    d["latency_ms"] = latency
                    d["status_detail"] = detail
                    d["snmp"] = snmp_data

                    # 若 NAS 成功採集到 SNMP 數據，同步儲存至 metrics_history
                    if snmp_data:
                        try:
                            from .models import DiskMetric, MetricsPayload
                            disk_metrics = [
                                DiskMetric(
                                    mount=v["mount"],
                                    total_gb=round(v["total_tb"] * 1024, 2),
                                    used_gb=round(v["used_tb"] * 1024, 2),
                                    percent=v["percent"],
                                )
                                for v in snmp_data.get("volumes", [])
                            ]
                            payload = MetricsPayload(
                                hostname=d["name"],
                                ip_address=d["ip_address"],
                                platform="Synology DSM",
                                cpu_percent=snmp_data["cpu_percent"],
                                memory_percent=snmp_data["memory_percent"],
                                memory_used_gb=snmp_data["memory_used_gb"],
                                memory_total_gb=snmp_data["memory_total_gb"],
                                disk=disk_metrics,
                                service_status={"dsm": "online", "snmp": "online"},
                            )
                            saved = await database.save(payload)
                            await broadcast({"type": "metric", "data": saved})
                        except Exception as ex:
                            logger.error(f"Error saving NAS telemetry for {d.get('name')}: {ex}")

                    updated_devices.append(d)
                else:
                    logger.error(f"Error probing device {d.get('name')}: {res}")

            if updated_devices:
                await broadcast({
                    "type": "devices_status",
                    "data": await database.list_devices()
                })
        except Exception as e:
            logger.error(f"Error in device probe scheduler: {e}")

        # 每 20 秒檢測一次
        await asyncio.sleep(20)
