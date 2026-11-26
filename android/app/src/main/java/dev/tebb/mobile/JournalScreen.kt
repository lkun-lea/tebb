package dev.tebb.mobile

import android.annotation.SuppressLint
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.AlertDialog
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 只传递本地阅读器的操作。任务身份与会话共享范围由宿主重新验证。 */
private class JournalActions(val onAction: (JSONObject) -> Unit) {
    @JavascriptInterface fun perform(raw: String) {
        if (raw.length <= 30000) runCatching { JSONObject(raw) }.getOrNull()?.let(onAction)
    }
}

/** 展示当前配对设备的待答和已共享回执；用户点选时长后仍可编辑，确认后才提交原任务。 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
internal fun JournalScreen(state: ChatUiState, paired: Boolean, back: () -> Unit, reply: (QuestionKey, String) -> Unit) {
    var ready by remember { mutableStateOf(false) }
    var source by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf<QuestionKey?>(null) }
    var notice by remember { mutableStateOf("") }
    var day by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        val format = SimpleDateFormat("yyyy-MM-dd", Locale.ROOT)
        while (true) { day = format.format(Date()); kotlinx.coroutines.delay(30000) }
    }
    val plans = remember(state.historySnapshot, paired) {
        val list = if (paired) JSONArray(state.historySnapshot) else JSONArray()
        List(list.length()) { list.getJSONObject(it) }
    }
    val pending = state.composer.pending.filter { paired && it.deviceId.isNotEmpty() }
    val snapshot = JSONObject().apply {
        put("day", day)
        put("reduceMotion", LocalReducedMotion.current)
        put("online", paired && state.connectionNotice == null)
        put("busy", state.work != null || state.composer.dictating)
        put("notice", notice.ifBlank { state.connectionNotice ?: state.notice ?: if (!paired) "配对 Windows 后可查看电脑任务。" else "" })
        put("questions", JSONArray().apply {
            for (q in pending.sortedByDescending { it.key == selected }) put(JSONObject().apply {
                put("conversation", q.conversation); put("run", q.key.runId); put("version", q.key.version)
                put("asked", q.asked); put("created", q.created); put("title", q.title); put("prompt", q.prompt)
            })
        })
        plans.mapNotNull { it.optJSONObject("today")?.optJSONObject("receipt") }
            .maxByOrNull { it.optLong("accepted") }?.let { put("receipt", it) }
        put("sections", JSONArray().apply {
            for ((slot,title) in listOf("morning" to "早报","project" to "项目时间线","evening" to "晚报")) {
                val rows = JSONArray()
                for (plan in plans) {
                    val items = plan.optJSONObject("today")?.optJSONObject("sections")?.optJSONArray(slot) ?: continue
                    for (i in 0 until items.length()) rows.put(JSONObject(items.getJSONObject(i).toString()).put("conversation",plan.getString("id")))
                }
                if (rows.length() > 0) put(JSONObject().put("title",title).put("rows",rows))
            }
        })
    }.toString()
    val act by rememberUpdatedState<(JSONObject) -> Unit> { action ->
        val key = QuestionKey(action.optString("run"), action.optString("version"))
        when (action.optString("type")) {
            "chat" -> back()
            "select" -> selected = key
            "source" -> {
                val cid = action.optString("conversation")
                if (plans.any { it.optString("id") == cid }) source = cid
                else notice = "在 Windows 共享原会话后，即可查看上下文。"
            }
            "answer" -> if (pending.any { it.key == key && it.conversation == action.optString("conversation") }) {
                notice = ""
                reply(key, action.optString("text"))
            }
        }
    }
    BackHandler { if (source.isNotEmpty()) source = "" else back() }
    AndroidView(factory = { context -> WebView(context).apply {
        settings.javaScriptEnabled = true
        settings.blockNetworkLoads = true
        settings.allowContentAccess = false
        settings.allowFileAccessFromFileURLs = false
        settings.allowUniversalAccessFromFileURLs = false
        addJavascriptInterface(JournalActions { action -> post { act(action) } }, "TebbJournal")
        webViewClient = object: WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = true
            override fun onPageFinished(view: WebView, url: String) { ready = url == "file:///android_asset/index.html" }
        }
        loadUrl("file:///android_asset/index.html")
    } }, modifier = Modifier.fillMaxSize(), onRelease = { it.removeJavascriptInterface("TebbJournal"); it.destroy() },
        update = { if (ready) it.evaluateJavascript("window.updateJournal(JSON.parse(" + JSONObject.quote(snapshot) + "))", null) })
    plans.firstOrNull { it.optString("id") == source }?.let { plan ->
        val rows = plan.optJSONArray("rows") ?: JSONArray()
        AlertDialog(onDismissRequest = { source = "" }, title = { Text(plan.optString("title")) },
            text = { Text((0 until rows.length()).joinToString("\n\n") { rows.getJSONObject(it).optString("text") }, Modifier.verticalScroll(rememberScrollState())) },
            confirmButton = { TextButton(onClick = { source = "" }) { Text("返回手记") } })
    }
}
