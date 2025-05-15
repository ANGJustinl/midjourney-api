"""
手动关联结果工具

当自动关联失败时，可以使用此工具手动关联放大图像与原始任务ID
"""

import argparse
import requests
import json

BASE_URL = "http://localhost:8000"

def link_result(trigger_id: str, image_url: str, hash_value: str = None):
    """关联图像结果到触发ID"""
    print(f"关联图像结果到触发ID: {trigger_id}")
    print(f"图像URL: {image_url}")
    
    # 首先注册映射关系
    if hash_value:
        print(f"使用哈希值: {hash_value}")
        try:
            response = requests.post(f"{BASE_URL}/v1/api/id_mapping/register", json={
                "primary_id": trigger_id,
                "related_id": hash_value
            })
            if response.status_code == 200:
                print("✅ 哈希映射成功")
            else:
                print(f"⚠️ 哈希映射失败: {response.text}")
        except Exception as e:
            print(f"⚠️ 哈希映射错误: {str(e)}")
    
    # 更新任务结果
    try:
        response = requests.post(f"{BASE_URL}/v1/api/status/update", json={
            "trigger_id": trigger_id,
            "result": {
                "image_urls": [image_url],
                "status": "completed"
            }
        })
        
        if response.status_code == 200:
            print("✅ 结果更新成功")
        else:
            print(f"⚠️ 结果更新失败: {response.text}")
            
        # 获取当前任务状态
        status_response = requests.get(f"{BASE_URL}/v1/api/status/{trigger_id}")
        if status_response.status_code == 200:
            status_data = status_response.json()
            print("\n当前任务状态:")
            print(json.dumps(status_data, indent=2))
        else:
            print(f"⚠️ 获取状态失败: {status_response.text}")
            
    except Exception as e:
        print(f"⚠️ 操作失败: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="手动关联图像结果到任务ID")
    parser.add_argument("trigger_id", help="任务ID")
    parser.add_argument("image_url", help="图像URL")
    parser.add_argument("--hash", "-H", help="相关哈希值")
    
    args = parser.parse_args()
    link_result(args.trigger_id, args.image_url, args.hash)

if __name__ == "__main__":
    main()
