"""
Discord消息监控工具

该工具可以独立运行，监控Discord频道中的新消息，
并将它们与API系统中的任务ID关联，特别是处理upscale等操作产生的新消息。
"""

import asyncio
import requests
from typing import Dict, List, Set, Optional
from loguru import logger

# API基础URL
API_URL = "http://localhost:8000"

# 存储最近处理的消息信息
processed_messages: Set[str] = set()
tracked_hashes: Dict[str, str] = {}  # hash -> trigger_id
tracked_trigger_ids: Set[str] = set()

async def fetch_recent_tasks(minutes: int = 10) -> List[Dict]:
    """从API获取最近的任务"""
    try:
        url = f"{API_URL}/v1/api/tasks/recent?minutes={minutes}"
        response = requests.get(url)
        if response.status_code == 200:
            tasks = response.json()
            logger.info(f"获取到{len(tasks)}个最近任务")
            return tasks
    except Exception as e:
        logger.error(f"获取最近任务失败: {e}")
    
    return []

async def process_discord_message(message: Dict) -> None:
    """处理Discord消息，尝试关联到API任务"""
    message_id = message.get("id")
    
    # 如果已处理过，跳过
    if message_id in processed_messages:
        return
    
    processed_messages.add(message_id)
    
    # 提取哈希值和关键信息
    hash_value = extract_hash(message)
    has_images = bool(message.get("attachments"))
    content = message.get("content", "")
    
    logger.info(f"处理消息: {message_id} (哈希: {hash_value}, 有图像: {has_images})")
    
    # 如果有哈希值，尝试找到关联的任务
    if hash_value:
        # 检查是否是已跟踪的哈希
        if hash_value in tracked_hashes:
            trigger_id = tracked_hashes[hash_value]
            logger.info(f"找到已跟踪的哈希关联: {hash_value} -> {trigger_id}")
            
            # 如果消息包含图像，更新任务结果
            if has_images:
                await update_task_result(trigger_id, message)
        else:
            # 尝试在API中查找关联
            trigger_id = await find_related_task(hash_value)
            if trigger_id:
                logger.info(f"在API中找到哈希关联: {hash_value} -> {trigger_id}")
                tracked_hashes[hash_value] = trigger_id
                tracked_trigger_ids.add(trigger_id)
                
                # 如果消息包含图像，更新任务结果
                if has_images:
                    await update_task_result(trigger_id, message)
            else:
                # 尝试查询最后一个正在执行的upscale任务
                last_task = await get_last_active_upscale()
                if last_task:
                    trigger_id = last_task.get("trigger_id")
                    logger.warning(f"未找到关联，尝试关联到最近upscale: {trigger_id}")
                    
                    # 注册映射关系
                    await register_mapping(trigger_id, hash_value)
                    
                    # 更新结果
                    if has_images:
                        await update_task_result(trigger_id, message)

async def extract_hash(message: Dict) -> Optional[str]:
    """从消息中提取哈希值"""
    # 从组件中提取
    components = message.get("components", [])
    for row in components:
        for component in row.get("components", []):
            custom_id = component.get("custom_id")
            if custom_id and "::" in custom_id:
                parts = custom_id.split("::")
                if len(parts) >= 5:
                    return parts[-1] if parts[-1] != "SOLO" else parts[-2]
    
    # 从URL中提取
    for row in components:
        for component in row.get("components", []):
            url = component.get("url")
            if url and "jobs/" in url:
                return url.split("jobs/")[-1].strip()
    
    return None

async def find_related_task(hash_value: str) -> Optional[str]:
    """查找与哈希值关联的任务ID"""
    try:
        url = f"{API_URL}/v1/api/id_mapping/search"
        response = requests.post(url, json={"hash": hash_value})
        if response.status_code == 200:
            data = response.json()
            return data.get("trigger_id")
    except Exception as e:
        logger.error(f"查找关联任务失败: {e}")
    
    return None

async def get_last_active_upscale() -> Optional[Dict]:
    """获取最后一个活跃的upscale任务"""
    try:
        url = f"{API_URL}/v1/api/tasks/active?type=upscale&limit=1"
        response = requests.get(url)
        if response.status_code == 200:
            tasks = response.json()
            if tasks:
                return tasks[0]
    except Exception as e:
        logger.error(f"获取活跃upscale任务失败: {e}")
    
    return None

async def register_mapping(trigger_id: str, hash_value: str) -> bool:
    """注册ID映射关系"""
    try:
        url = f"{API_URL}/v1/api/id_mapping/register"
        response = requests.post(url, json={"primary_id": trigger_id, "related_id": hash_value})
        if response.status_code == 200:
            tracked_hashes[hash_value] = trigger_id
            tracked_trigger_ids.add(trigger_id)
            logger.info(f"注册ID映射成功: {hash_value} -> {trigger_id}")
            return True
    except Exception as e:
        logger.error(f"注册ID映射失败: {e}")
    
    return False

async def update_task_result(trigger_id: str, message: Dict) -> None:
    """更新任务结果"""
    try:
        # 提取图像URL
        attachments = message.get("attachments", [])
        image_urls = [a.get("url") for a in attachments if a.get("url")]
        
        if not image_urls:
            logger.warning(f"消息没有图像附件: {message.get('id')}")
            return
        
        # 更新任务结果
        data = {
            "trigger_id": trigger_id,
            "status": "completed",
            "result": {
                "image_urls": image_urls,
                "message_id": message.get("id"),
                "content": message.get("content", "")
            }
        }
        
        url = f"{API_URL}/v1/api/status/update"
        response = requests.post(url, json=data)
        if response.status_code == 200:
            logger.info(f"更新任务结果成功: {trigger_id} - {len(image_urls)}个图像")
            return True
    except Exception as e:
        logger.error(f"更新任务结果失败: {e}")
    
    return False

async def watch_discord():
    """监控Discord频道的新消息"""
    logger.info("开始监控Discord消息...")
    
    # 持续监控
    while True:
        try:
            # 获取最近的Discord消息
            url = f"{API_URL}/v1/api/discord/messages?limit=10"
            response = requests.get(url)
            
            if response.status_code == 200:
                messages = response.json()
                for message in messages:
                    await process_discord_message(message)
            else:
                logger.error(f"获取Discord消息失败: {response.status_code}")
        
        except Exception as e:
            logger.error(f"监控过程中出错: {e}")
        
        # 等待一段时间再次检查
        await asyncio.sleep(2)

async def main():
    """主函数"""
    # 设置日志
    logger.add("discord_watch.log", rotation="500 MB")
    
    try:
        # 获取最近的任务，用于初始化跟踪状态
        tasks = await fetch_recent_tasks(30)
        for task in tasks:
            trigger_id = task.get("trigger_id")
            if task.get("type") == "upscale":
                tracked_trigger_ids.add(trigger_id)
                
                # 如果任务有哈希值，也记录下来
                result = task.get("result", {})
                if result.get("msg_hash"):
                    hash_value = result["msg_hash"]
                    tracked_hashes[hash_value] = trigger_id
        
        # 启动监控
        await watch_discord()
        
    except KeyboardInterrupt:
        logger.info("监控已停止")
    except Exception as e:
        logger.error(f"运行过程中出错: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
