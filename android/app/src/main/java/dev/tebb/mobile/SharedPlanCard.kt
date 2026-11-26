package dev.tebb.mobile

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject

/** 一次完整、可原子替换的设备投影。时间为 Windows 核对时的毫秒值。 */
internal data class DeviceSnapshot(val time: Long, val rows: List<PendingQuestion>, val history: String, val modelConfig: String? = null) {
    override fun toString(): String = "DeviceSnapshot(time=$time, rows=${rows.size})"
}

private fun JSONArray.objects() = List(length()) { getJSONObject(it) }
private fun evidenceTime(plan: JSONObject) = plan.getJSONArray("rows").objects().maxOfOrNull { it.optLong("time") } ?: 0L
private fun version(plan: JSONObject) = plan.getString("id") + "/" + evidenceTime(plan) + "/" + plan.getInt("total")

/** 用户可随时查看已共享的旧资料；近期推荐单独征得同意，跳过与纠正均绑定来源版本。 */
@Composable
internal fun SharedPlanCard(owner: String, computer: String, raw: String, offline: String?, canEdit: Boolean, draft: (String) -> Unit) {
    val context = LocalContext.current
    val prefs = remember(owner,computer) { context.getSharedPreferences("plan_card_${owner}_$computer", Context.MODE_PRIVATE) }
    val plans = remember(raw) { JSONArray(raw).objects().sortedByDescending(::evidenceTime) }
    var selected by remember(prefs) { mutableStateOf("") }
    var show by remember(prefs) { mutableStateOf(false) }
    var allowed by remember(prefs) { mutableStateOf(prefs.getBoolean("allowed", false)) }
    var hidden by remember(prefs) { mutableStateOf(prefs.getStringSet("hidden", emptySet()).orEmpty().toSet()) }
    var corrected by remember(prefs) { mutableStateOf(prefs.getStringSet("corrected", emptySet()).orEmpty().toSet()) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()/1000) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis()/1000; kotlinx.coroutines.delay(60_000) } }
    val recent = plans.firstOrNull { it.getString("id") !in corrected && version(it) !in hidden && now - evidenceTime(it) in 0L..7L*86400 }
    val current = plans.find { it.getString("id") == selected }
    fun ignore(plan: JSONObject) {
        hidden = hidden + version(plan)
        prefs.edit().putStringSet("hidden", hidden).apply()
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp)) {
        if (allowed && recent != null) {
            val quote = recent.getJSONArray("rows").objects().lastOrNull { it.optString("kind") == "原文" }
            if (quote != null) Text(quote.getString("text"), maxLines = 2, color = androidx.compose.ui.graphics.Color.White)
        }
        Row {
            TextButton(onClick = { selected = ""; show = true }) { Text("已共享方案") }
            if (recent != null && !allowed) {
                TextButton(onClick = { allowed = true; prefs.edit().putBoolean("allowed", true).apply() }) { Text("用这些会话推荐下一步") }
                TextButton(onClick = { ignore(recent) }) { Text("跳过") }
            } else if (recent != null) {
                TextButton(onClick = { selected = recent.getString("id"); show = true }) { Text("继续 · " + recent.getString("title"), maxLines = 1) }
            }
        }
    }
    if (!show) return
    AlertDialog(onDismissRequest = { show = false }, title = { Text(current?.getString("title") ?: "已共享方案") },
        text = { Column(Modifier.verticalScroll(rememberScrollState())) {
            offline?.let { Text(it) }
            if (current == null) plans.forEach { plan ->
                TextButton(onClick = { selected = plan.getString("id") }) { Text(plan.getString("title")) }
            } else {
                val rows = current.getJSONArray("rows").objects()
                Text("Windows · 已保留 ${rows.size}/${current.getInt("total")} 条")
                rows.forEach { row ->
                    val time = row.optLong("time")
                    Text((if (time > 0) android.text.format.DateFormat.format("yyyy-MM-dd HH:mm",time*1000).toString() else "时间未知") +
                        " · " + row.getString("kind") + " · " + row.getString("source"))
                    Text(row.getString("text") + if (row.optBoolean("truncated")) "…" else "")
                }
                if (rows.isEmpty()) Text("当前会话没有留存原文")
                fun matters(plan: JSONObject): Set<String> {
                    val ids = plan.optJSONArray("matters") ?: return emptySet()
                    return (0 until ids.length()).map(ids::getString).toSet()
                }
                val itemIds = matters(current)
                plans.filter { it !== current && matters(it).intersect(itemIds).isNotEmpty() }.forEach { other ->
                    TextButton(onClick = { selected = other.getString("id") }) { Text("同一事项 · " + other.getString("title")) }
                }
                val related = plans.filter { it !== current && matters(it).intersect(itemIds).isEmpty() && current.optString("project").isNotEmpty() && it.optString("project") == current.optString("project") }
                related.forEach { other -> TextButton(onClick = { selected = other.getString("id") }) { Text("同项目 · " + other.getString("title")) } }
                TextButton(enabled = canEdit && rows.isNotEmpty(), onClick = {
                    val row = rows.last()
                    draft("继续梳理《" + current.getString("title") + "》\n依据 " + row.getString("source") + "：" + row.getString("text")); show = false
                }) { Text("引用到本地草稿") }
                TextButton(onClick = {
                    corrected = corrected + current.getString("id")
                    prefs.edit().putStringSet("corrected", corrected).apply()
                    show = false
                }) { Text("这不是当前工作") }
            }
        } }, confirmButton = { TextButton(onClick = { show = false }) { Text("关闭") } })
}
