package dev.tebb.mobile

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.activity.compose.setContent
import org.json.JSONArray
import org.json.JSONObject

/** 在隔离安装的手机验收包中，用实际 Compose 页面核对来源、项目关联和纠正。 */
class PersonalAgentAcceptance : Instrumentation() {
    private var live = false

    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        live = arguments?.getString("live") == "true"
        start()
    }

    private fun findText(node: AccessibilityNodeInfo?, value: String): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.text?.toString() == value || node.contentDescription?.toString() == value) return node
        for (i in 0 until node.childCount) findText(node.getChild(i), value)?.let { return it }
        return null
    }

    private fun waitFor(value: String): AccessibilityNodeInfo {
        val deadline = SystemClock.elapsedRealtime() + 8000
        do {
            findText(uiAutomation.rootInActiveWindow, value)?.let { return it }
            SystemClock.sleep(100)
        } while (SystemClock.elapsedRealtime() < deadline)
        error("未找到控件：$value")
    }

    private fun tap(value: String) {
        var node: AccessibilityNodeInfo? = waitFor(value)
        while (node != null) {
            if (node.isClickable && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return
            node = node.parent
        }
        error("控件不可点击：$value")
    }

    override fun onStart() {
        val report = Bundle()
        var activity: Activity? = null
        try {
            val intent = Intent().setClassName(targetContext, "dev.tebb.mobile.MainActivity").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            val screen = startActivitySync(intent) as MainActivity
            activity = screen
            val now = System.currentTimeMillis()/1000
            fun plan(id: String, title: String, project: String, time: Long) =
                JSONObject().put("id", id).put("title", title).put("project", project).put("total", 1)
                    .put("rows", JSONArray().put(JSONObject().put("kind", "原文").put("source", "证据-$id")
                        .put("time", time).put("text", "原文-$title")))
            val archived = plan("archive", "夏季方案", "历史", now-100L*86400)
            val rows = JSONArray().put(archived).put(plan("a", "中转设计", "tebb", now)).put(plan("b", "配对讨论", "tebb", now-60))
                .put(plan("c", "报销讨论", "费用", now-120))
            rows.getJSONObject(1).put("today", JSONObject().put("date", "2026-11-26")
                .put("sections", JSONObject().put("morning", JSONArray().put(JSONObject().put("title","复核中转设计")))))
            val invite = JSONObject().put("owner","fixture").put("host","192.168.1.1").put("port",1234)
                .put("pin","0".repeat(64)).put("v",2).put("id","fixture-device")
            val isolated = object : android.content.ContextWrapper(targetContext) {
                override fun getSharedPreferences(name: String?, mode: Int) =
                    super.getSharedPreferences("instrumentation-cache-" + name, mode)
            }
            val paired = PairingClient(invite)
            val cachedAt = now * 1000 - 120_000
            paired.cache(isolated,DeviceSnapshot(cachedAt,emptyList(),rows.toString()))
            check(PairingClient(JSONObject(invite.toString()).put("owner","other")).cached(isolated) == null)
            val saved = checkNotNull(paired.cached(isolated))
            check(saved.time == cachedAt)
            paired.clearCache(isolated)
            check(paired.cached(isolated) == null)
            val owner = "fixture-" + java.util.UUID.randomUUID()
            val draft = java.util.concurrent.atomic.AtomicReference("")
            runOnMainSync {
                screen.setContent { SharedPlanCard(owner, "测试电脑", saved.history, "Windows 缓存 · 已离线", true) { draft.set(it) } }
            }
            tap("已共享方案")
            tap("夏季方案")
            waitFor("Windows 缓存 · 已离线")
            waitFor("原文-夏季方案")
            tap("关闭")
            tap("用这些会话推荐下一步")
            tap("继续 · 中转设计")
            waitFor("原文-中转设计")
            check(findText(uiAutomation.rootInActiveWindow,"同项目 · 报销讨论") == null)
            tap("同项目 · 配对讨论")
            waitFor("原文-配对讨论")
            tap("引用到本地草稿")
            waitFor("已共享方案")
            waitForIdleSync()
            check("证据-b" in draft.get() && "原文-配对讨论" in draft.get()) { "引用的原文与当前会话不一致" }
            tap("继续 · 中转设计")
            tap("这不是当前工作")
            waitFor("继续 · 配对讨论")
            check(findText(uiAutomation.rootInActiveWindow,"继续 · 中转设计") == null)
            runOnMainSync {
                val pairing = PairingViewModel(screen.application, androidx.lifecycle.SavedStateHandle())
                screen.setContent {
                    androidx.compose.material.MaterialTheme(colors = androidx.compose.material.darkColors()) {
                        PairingPanel(pairing, onSignOut = {}, onDecode = {})
                    }
                }
            }
            waitFor("刷新电脑状态")
            waitFor("扫码配对 Windows")
            waitFor("从图片识别配对码")
            val review = PendingQuestion(QuestionKey(owner,"v1"), "评审安排", "评审多久？", "dm-tebb", "windows")
            val received = java.util.concurrent.atomic.AtomicReference("")
            val submitted = java.util.concurrent.CountDownLatch(1)
            runOnMainSync {
                screen.setContent {
                    JournalScreen(ChatUiState(ComposerState(pending=listOf(review)), historySnapshot=saved.history), true, {}) { key, answer ->
                        check(key == review.key)
                        received.set(answer)
                        submitted.countDown()
                    }
                }
            }
            waitFor("早报")
            tap("复核中转设计")
            waitFor("原文-中转设计")
            tap("返回手记")
            tap("45 分钟")
            waitForIdleSync()
            runOnMainSync { screen.setContent { androidx.compose.material.Text("离开手记") } }
            waitFor("离开手记")
            runOnMainSync {
                screen.setContent {
                    JournalScreen(ChatUiState(ComposerState(pending=listOf(review)), historySnapshot=saved.history), true, {}) { key, answer ->
                        check(key == review.key)
                        received.set(answer)
                        submitted.countDown()
                    }
                }
            }
            val enabledDeadline = SystemClock.elapsedRealtime() + 5000
            while (!waitFor("回复原任务").isEnabled && SystemClock.elapsedRealtime() < enabledDeadline) {
                SystemClock.sleep(100)
            }
            check(waitFor("回复原任务").isEnabled) { "选中时长后提交按钮仍未启用" }
            tap("回复原任务")
            waitForIdleSync()
            check(submitted.await(5, java.util.concurrent.TimeUnit.SECONDS) && received.get() == "45 分钟") { "本地阅读器未提交选中的时长" }
            runOnMainSync { screen.setContent { WorkspaceEntry("agent.request", owner, saved.history) {} } }
            tap("选择已共享会话")
            tap("中转设计")
            waitFor("想让伙伴做什么？")
            runOnMainSync { screen.setContent { WorkspaceEntry("note.create", owner, saved.history) {} } }
            waitFor("新增笔记")
            waitFor("正文")
            check(generateSequence(waitFor("保存到电脑")) { it.parent }.any { !it.isEnabled }) { "未配对时不能写入电脑" }
            runOnMainSync { screen.setContent { WorkspaceEntry("calendar.create", owner, saved.history) {} } }
            waitFor("查看最近新增的日程")
            runOnMainSync { screen.setContent { MobileWorkspace(ChatUiState(ComposerState()), owner, true, {}, { _, _ -> }, {}, {}) } }
            tap("笔记")
            tap("手动新增笔记")
            waitFor("正文")
            tap("返回笔记")
            tap("知识库")
            tap("让伙伴处理资料")
            waitFor("请先在电脑共享一个会话")
            if (live) {
                val url = java.net.URL("https://8.136.145.17/cloud/v1/device-snapshot?device=" + "0".repeat(32) + "&stream=windows")
                val http = url.openConnection() as javax.net.ssl.HttpsURLConnection
                try {
                    http.connectTimeout = 10000
                    http.readTimeout = 10000
                    http.instanceFollowRedirects = false
                    check(http.responseCode == 401) { "真实 ECS 未拒绝匿名读取" }
                } finally { http.disconnect() }
            }
            report.putString("stream", "PASS 缓存时间、账号隔离、离线旧方案、来源、授权、同项目、排除干扰、引用、纠正\n")
            finish(Activity.RESULT_OK, report)
        } catch (e: Exception) {
            report.putString("stream", "FAIL " + e.toString() + "\n")
            finish(Activity.RESULT_CANCELED, report)
        } finally {
            activity?.let { runOnMainSync { it.finish() } }
        }
    }
}

