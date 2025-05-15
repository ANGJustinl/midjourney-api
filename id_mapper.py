"""
ID映射辅助模块

该模块提供一系列工具函数用于关联不同系统(API、Discord)之间的ID，
并能基于启发式算法自动匹配未明确映射的ID。
"""

from datetime import datetime
from typing import Dict, List, Set, Tuple, Any
from loguru import logger

# 全局映射数据
id_mappings: Dict[str, str] = {}
trigger_times: Dict[str, datetime] = {}
active_tasks: List[str] = []
# 新增哈希映射
hash_mappings: Dict[str, str] = {}

# 添加操作历史记录
operation_history: Dict[str, List[Dict[str, Any]]] = {}

def register_mapping(origin_id: str, related_id: str) -> None:
    """注册ID映射，建立不同ID系统之间的关联"""
    global id_mappings
    id_mappings[related_id] = origin_id
    id_mappings[origin_id] = origin_id  # 自映射
    
    # 记录时间
    if origin_id not in trigger_times:
        trigger_times[origin_id] = datetime.now()
    
    logger.debug(f"ID映射: {related_id} -> {origin_id}")
    
    # 如果不在活动任务中，添加它
    if origin_id not in active_tasks:
        active_tasks.append(origin_id)
        
    # 如果是哈希值格式，也加入哈希映射
    if "-" in related_id and len(related_id) > 30:
        hash_mappings[related_id] = origin_id
        logger.info(f"添加哈希映射: {related_id} -> {origin_id}")

def get_original_id(any_id: str) -> str:
    """通过任何关联ID获取原始触发ID"""
    # 1. 直接映射查找
    if any_id in id_mappings:
        return id_mappings[any_id]
        
    # 2. 尝试通过哈希映射查找
    if any_id in hash_mappings:
        return hash_mappings[any_id]
        
    # 3. 尝试部分匹配哈希(处理截断情况)
    if len(any_id) > 8:
        for hash_key in hash_mappings:
            if hash_key.startswith(any_id) or any_id.startswith(hash_key):
                logger.info(f"通过部分哈希匹配: {any_id} ~= {hash_key} -> {hash_mappings[hash_key]}")
                return hash_mappings[hash_key]
    
    # 4. 尝试推断 - 使用时间最近的活动任务
    if active_tasks:
        latest_id = active_tasks[-1]
        logger.warning(f"无映射，使用最近任务: {any_id} -> {latest_id}")
        register_mapping(latest_id, any_id)  # 创建映射防止下次再查找
        return latest_id
        
    # 5. 返回原ID
    return any_id

def record_operation(trigger_id: str, operation_type: str, hash_value: str = None) -> None:
    """记录操作历史，用于关联后续结果"""
    if trigger_id not in operation_history:
        operation_history[trigger_id] = []
    
    operation_history[trigger_id].append({
        "type": operation_type,
        "hash": hash_value,
        "time": datetime.now()
    })
    
    logger.debug(f"记录操作历史: {trigger_id} - {operation_type} - {hash_value}")

def get_operations_by_hash(hash_value: str) -> List[Tuple[str, str]]:
    """通过哈希值查找相关操作历史"""
    results = []
    
    # 首先尝试精确匹配
    for tid, operations in operation_history.items():
        for op in operations:
            if op["hash"] == hash_value:
                results.append((tid, op["type"]))
                
    # 如果没有精确匹配，尝试部分匹配
    if not results and hash_value and len(hash_value) > 8:
        hash_prefix = hash_value[:8]
        hash_suffix = hash_value[-8:]
        
        for tid, operations in operation_history.items():
            for op in operations:
                if op["hash"] and (
                    (hash_prefix in op["hash"]) or 
                    (hash_suffix in op["hash"]) or
                    (op["hash"][:8] in hash_value) or
                    (op["hash"][-8:] in hash_value)
                ):
                    results.append((tid, op["type"]))
    
    return results

def find_related_ids(trigger_id: str) -> Set[str]:
    """查找与给定ID关联的所有ID"""
    result = {trigger_id}
    
    # 首先获取原始ID
    origin_id = get_original_id(trigger_id)
    result.add(origin_id)
    
    # 搜索所有映射到同一原始ID的ID
    for id_key, id_value in id_mappings.items():
        if id_value == origin_id:
            result.add(id_key)
            
    # 搜索哈希映射
    for hash_key, hash_value in hash_mappings.items():
        if hash_value == origin_id or hash_value in result:
            result.add(hash_key)
            
    # 双向检查，查找所有可能的中介关联
    for id_key, id_value in id_mappings.items():
        if id_key in result or id_value in result:
            result.add(id_key)
            result.add(id_value)
    
    # 检查操作历史中的哈希值
    if origin_id in operation_history:
        for op in operation_history[origin_id]:
            if op["hash"]:
                result.add(op["hash"])
    
    return result

def clean_inactive_tasks(timeout_minutes: int = 30) -> None:
    """清理不活跃的任务记录"""
    now = datetime.now()
    to_remove = []
    
    for task_id, task_time in trigger_times.items():
        if (now - task_time).total_seconds() > timeout_minutes * 60:
            to_remove.append(task_id)
    
    for task_id in to_remove:
        try:
            active_tasks.remove(task_id)
        except ValueError:
            pass
        trigger_times.pop(task_id, None)
        
    # 清理映射
    to_remove_mappings = [k for k, v in id_mappings.items() if v in to_remove]
    for key in to_remove_mappings:
        id_mappings.pop(key, None)
    
    # 清理哈希映射
    to_remove_hashes = [k for k, v in hash_mappings.items() if v in to_remove]
    for key in to_remove_hashes:
        hash_mappings.pop(key, None)
    
    logger.debug(f"清理了 {len(to_remove)} 个过期任务ID")

def register_task_start(trigger_id: str) -> None:
    """注册任务开始"""
    if trigger_id not in active_tasks:
        active_tasks.append(trigger_id)
    trigger_times[trigger_id] = datetime.now()
    register_mapping(trigger_id, trigger_id)  # 自映射
    logger.debug(f"注册任务开始: {trigger_id}")

def register_task_end(trigger_id: str) -> None:
    """注册任务结束"""
    try:
        active_tasks.remove(trigger_id)
        logger.debug(f"注册任务结束: {trigger_id}")
    except ValueError:
        pass
