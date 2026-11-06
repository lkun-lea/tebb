"""离线运行真实资讯 worker 协议，禁止调用真实飞书。"""
from unittest.mock import patch
from desk_companion.content.news import service as news
from desk_companion.integrations.feishu import feishu_tools
from desk_companion.tasks.worker import main

items = [{"id": str(i), "title": f"官方资料{i}", "url": f"https://github.com/example/repo{i}", "summary": "离线事实",
          "value": "离线建议", "caution": "样本", "category": "工具", "published": "", "date_verified": False} for i in range(5)]
with patch.object(news, "collect", return_value=(items, [])), \
     patch.object(news, "summarize", return_value={"lead": "离线流程正常", "items": items, "candidate_count": 5}), \
     patch.object(feishu_tools, "_run_lark", side_effect=AssertionError("不得调用个人账号")):
    main()
