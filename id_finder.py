"""
ID关联查找工具

这个工具用于查询和分析API中不同ID之间的关联
"""

import argparse
import json
import requests
from typing import Dict, Any, Set, Optional

# API基础地址
BASE_URL = "http://localhost:8000"

def get_task_status(trigger_id: str) -> Optional[Dict[str, Any]]:
    """获取任务状态"""
    try:
        response = requests.get(f"{BASE_URL}/v1/api/status/{trigger_id}")
        if response.status_code == 200:
            return response.json()
        print(f"获取状态失败: {response.status_code}")
        return None
    except Exception as e:
        print(f"错误: {str(e)}")
        return None

def find_related_ids(trigger_id: str) -> Set[str]:
    """查找与给定ID相关的所有ID"""
    result = set([trigger_id])
    to_check = [trigger_id]
    checked = set()
    
    print(f"搜索与 {trigger_id} 相关的ID...")
    
    while to_check:
        current_id = to_check.pop(0)
        if current_id in checked:
            continue
            
        checked.add(current_id)
        print(f"检查ID: {current_id}")
        
        # 查询当前ID的状态
        status = get_task_status(current_id)
        if not status:
            continue
            
        # 从结果中寻找可能的关联ID
        if "result" in status and status["result"]:
            result_data = status["result"]
            
            # 检查常见ID字段
            for id_field in ["message_id", "job_id", "hash"]:
                if id_field in result_data and result_data[id_field]:
                    related_id = str(result_data[id_field])
                    if related_id and related_id not in result:
                        print(f"  发现相关ID: {related_id} ({id_field})")
                        result.add(related_id)
                        to_check.append(related_id)
    
    print(f"\n找到 {len(result)} 个相关ID:")
    for rid in result:
        print(f"  - {rid}")
    
    return result

def build_composite_status(trigger_id: str) -> Dict[str, Any]:
    """构建组合状态，整合所有相关ID的信息"""
    related_ids = find_related_ids(trigger_id)
    composite = {
        "trigger_id": trigger_id,
        "related_ids": list(related_ids),
        "status": "unknown",
        "results": {}
    }
    
    print("\n收集所有相关ID的状态...\n")
    
    for rid in related_ids:
        status = get_task_status(rid)
        if status:
            composite["results"][rid] = status
            
            # 更新组合状态
            if status.get("status") == "completed" and composite["status"] != "completed":
                composite["status"] = "completed"
                composite["completed_id"] = rid
            elif status.get("status") == "generating" and composite["status"] not in ["completed"]:
                composite["status"] = "generating"
            elif status.get("status") == "pending" and composite["status"] == "unknown":
                composite["status"] = "pending"
    
    return composite

def main():
    parser = argparse.ArgumentParser(description="ID关联查找工具")
    parser.add_argument("trigger_id", help="要查询的触发ID")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    parser.add_argument("--output", "-o", type=str, help="将结果保存至文件")
    args = parser.parse_args()
    
    composite = build_composite_status(args.trigger_id)
    
    if composite["status"] == "completed":
        print(f"\n✅ 任务已完成! 完成ID: {composite['completed_id']}")
        
        # 显示图像URL和哈希
        completed_data = composite["results"].get(composite["completed_id"], {})
        if "result" in completed_data and completed_data["result"]:
            result = completed_data["result"]
            
            if "image_urls" in result and result["image_urls"]:
                print("\n图像URL:")
                for i, url in enumerate(result["image_urls"]):
                    print(f"  {i+1}. {url}")
            
            if "hash" in result:
                print(f"\n哈希值: {result['hash']}")
            
            if "message_id" in completed_data:
                print(f"消息ID: {completed_data['message_id']}")
                
    elif composite["status"] == "generating":
        print("\n⏳ 任务正在进行中...")
    else:
        print(f"\n❓ 任务状态: {composite['status']}")
    
    # 保存详细输出
    if args.verbose:
        print("\n详细信息:")
        print(json.dumps(composite, indent=2))
        
    if args.output:
        with open(args.output, "w") as f:
            json.dump(composite, f, indent=2)
        print(f"\n结果已保存至: {args.output}")

if __name__ == "__main__":
    main()
