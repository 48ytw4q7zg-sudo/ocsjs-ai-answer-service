# -*- coding: utf-8 -*-
"""测试脚本 v2.1.0 — 用于测试 AI 题库服务是否正常工作"""
import requests
import json
import sys
import os
from dotenv import load_dotenv

load_dotenv()

SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:5000")


def test_health():
    """测试健康检查接口"""
    print("测试健康检查接口...")
    try:
        response = requests.get(f"{SERVICE_URL}/api/health")
        print(f"状态码: {response.status_code}")
        data = response.json()
        print(f"响应内容: {json.dumps(data, indent=2, ensure_ascii=False)}")

        # 验证 v2.1.0 新增字段
        if data.get("status") != "ok":
            print("健康检查状态异常！")
            return False
        if "base_url" in data:
            print(f"  [v2.1] base_url: {data['base_url']}")
        if "ccswitch" in data:
            ccs = data["ccswitch"]
            print(f"  [v2.1] ccswitch raw_model: {ccs.get('raw_model')}")
            print(f"  [v2.1] ccswitch is_proxy: {ccs.get('is_proxy')}")
            print(f"  [v2.1] model_sanitized: {ccs.get('model_sanitized')}")
        if "config_keys" in data:
            print(f"  [v2.1] config_keys count: {len(data['config_keys'])}")

        print("健康检查接口测试成功！\n")
        return True
    except Exception as e:
        print(f"健康检查接口测试失败: {e}\n")
        return False


def test_config_reload():
    """测试配置重载接口 (v2.1.0)"""
    print("测试配置重载接口...")
    try:
        response = requests.post(f"{SERVICE_URL}/api/config/reload")
        data = response.json()
        print(f"状态码: {response.status_code}")
        print(f"响应内容: {json.dumps(data, indent=2, ensure_ascii=False)}")
        if data.get("success"):
            print(f"  配置来源: {data.get('config_source')}")
            print(f"  模型: {data.get('model')}")
            print("配置重载接口测试成功！\n")
            return True
        else:
            print(f"配置重载接口测试失败: {data.get('message')}\n")
            return False
    except Exception as e:
        print(f"配置重载接口测试失败: {e}\n")
        return False


def test_search(question, question_type=None, options=None):
    """测试搜索接口"""
    print(f"测试搜索接口: {question}")

    params = {"title": question}
    if question_type:
        params["type"] = question_type
    if options:
        params["options"] = options

    try:
        print("发送请求...")
        print(f"参数: {json.dumps(params, indent=2, ensure_ascii=False)}")

        response = requests.get(f"{SERVICE_URL}/api/search", params=params)

        print(f"状态码: {response.status_code}")
        result = response.json()
        print(f"响应内容: {json.dumps(result, indent=2, ensure_ascii=False)}")

        if result.get("code") == 1:
            print("搜索接口测试成功！\n")
            return True
        else:
            print(f"搜索接口测试失败: {result.get('msg', '未知错误')}\n")
            return False
    except Exception as e:
        print(f"搜索接口测试失败: {e}\n")
        return False


def test_stats():
    """测试统计接口 (v2.1.0 增强)"""
    print("测试统计接口...")
    try:
        response = requests.get(f"{SERVICE_URL}/api/stats")
        data = response.json()
        print(f"状态码: {response.status_code}")
        print(f"响应内容: {json.dumps(data, indent=2, ensure_ascii=False)}")
        if data.get("version"):
            print(f"  [v2.1] base_url: {data.get('base_url', 'N/A')}")
            print(f"  [v2.1] ccswitch_raw_model: {data.get('ccswitch_raw_model', 'N/A')}")
            print("统计接口测试成功！\n")
            return True
        return False
    except Exception as e:
        print(f"统计接口测试失败: {e}\n")
        return False


def main():
    """主测试函数"""
    print("=" * 50)
    print("AI题库服务测试脚本 v2.1.0")
    print("=" * 50)

    # 1. 健康检查
    if not test_health():
        print("健康检查失败，请确认服务是否正常运行。")
        sys.exit(1)

    # 2. 配置重载 (v2.1.0)
    test_config_reload()

    # 3. 统计接口 (v2.1.0)
    test_stats()

    # 4. 单选题
    test_search(
        "中国的首都是哪个城市？",
        "single",
        "A. 上海\nB. 北京\nC. 广州\nD. 深圳"
    )

    # 5. 多选题
    test_search(
        "以下哪些是中国的一线城市？",
        "multiple",
        "A. 北京\nB. 上海\nC. 广州\nD. 深圳\nE. 成都\nF. 杭州"
    )

    # 6. 判断题
    test_search(
        "地球是太阳系中第三颗行星。",
        "judgement"
    )

    # 7. 填空题
    test_search(
        "《红楼梦》的作者是_______。",
        "completion"
    )

    print("=" * 50)
    print("测试完成！")
    print("=" * 50)


if __name__ == "__main__":
    main()
