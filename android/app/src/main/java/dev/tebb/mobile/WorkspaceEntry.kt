package dev.tebb.mobile

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.content.Context
import android.text.format.DateUtils
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.UUID

/** 手动新增入口。每个账号和配对设备独立保存草稿，电脑确认后才清空。 */
@Composable
internal fun WorkspaceEntry(action: String, owner: String, history: String, returnLabel: String = "返回主聊", eventJson: String = "", back: () -> Unit) {
    val context = LocalContext.current
    val device = PairingClient.approved(context)?.pairedId
    val event = remember(eventJson) { eventJson.takeIf { it.isNotEmpty() }?.let(::JSONObject) }
    val suffix = event?.getString("id")?.let { ".$it" }.orEmpty()
    val prefs = remember(owner, device, action, suffix) {
        context.getSharedPreferences("entry.$owner.$device.$action$suffix", Context.MODE_PRIVATE)
    }
    val agent = action == "agent.request"
    val chats = remember(history) {
        val rows = org.json.JSONArray(history)
        List(rows.length()) { rows.getJSONObject(it) }.associate { it.getString("id") to it.getString("title") }
    }
    var selectedEvent by remember(prefs) { mutableStateOf(prefs.getString("event", event?.getString("id")).orEmpty()) }
    var version by remember(prefs) { mutableStateOf(prefs.getInt("version", event?.getInt("version") ?: 0)) }
    var calendarRows by remember { mutableStateOf(emptyList<JSONObject>()) }
    var showEvents by remember { mutableStateOf(false) }
    var conversation by remember(prefs) { mutableStateOf(prefs.getString("conversation", "").orEmpty()) }
    var choosing by remember { mutableStateOf(false) }
    val calendar = action == "calendar.create"
    val scope = rememberCoroutineScope()
    var title by remember(prefs) { mutableStateOf(prefs.getString("title", event?.getString("summary")).orEmpty()) }
    var body by remember(prefs) { mutableStateOf(prefs.getString("body", "").orEmpty()) }
    val eventTime = remember(eventJson) { SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ROOT) }
    var start by remember(prefs) { mutableStateOf(prefs.getLong("start", event?.let { eventTime.parse(it.getString("start"))?.time } ?: (System.currentTimeMillis() + 3600000))) }
    var end by remember(prefs) { mutableStateOf(prefs.getLong("end", event?.let { eventTime.parse(it.getString("end"))?.time } ?: (start + 1800000))) }
    var busy by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf("") }
    fun saveDraft() {
        prefs.edit().putString("title", title).putString("body", body)
            .putString("event", selectedEvent).putInt("version", version).putString("conversation", conversation).putLong("start", start).putLong("end", end).apply()
    }
    fun pick(value: Long, set: (Long) -> Unit) {
        val date = Calendar.getInstance().apply { timeInMillis = value }
        DatePickerDialog(context, { _, year, month, day ->
            TimePickerDialog(context, { _, hour, minute ->
                date.set(year, month, day, hour, minute, 0)
                set(date.timeInMillis)
                saveDraft()
            }, date.get(Calendar.HOUR_OF_DAY), date.get(Calendar.MINUTE), true).show()
        }, date.get(Calendar.YEAR), date.get(Calendar.MONTH), date.get(Calendar.DAY_OF_MONTH)).show()
    }
    BackHandler { if (!busy) back() }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        TextButton(onClick = back, enabled = !busy) { Text(returnLabel) }
        Text(if (agent) "交给电脑伙伴" else if (calendar) "日程" else "新增笔记", style = MaterialTheme.typography.h4)
        if (calendar && event == null) {
            TextButton(enabled = !busy, onClick = {
                val client = PairingClient.approved(context) ?: return@TextButton
                busy = true
                scope.launch {
                    try {
                        val ack = withContext(Dispatchers.IO) { client.create("calendar.list", UUID.randomUUID().toString(), JSONObject()) }
                        val rows = ack.getJSONArray("events")
                        calendarRows = List(rows.length()) { rows.getJSONObject(it) }
                        showEvents = calendarRows.isNotEmpty()
                        notice = if (showEvents) "" else "还没有通过这台手机新增的日程"
                    } catch (e: CancellationException) { throw e }
                    catch (e: Exception) { notice = e.message ?: "读取失败" }
                    finally { busy = false }
                }
            }) { Text("查看最近新增的日程") }
            DropdownMenu(showEvents, { showEvents = false }) {
                calendarRows.forEach { row -> DropdownMenuItem({
                    selectedEvent = row.getString("id"); version = row.getInt("version")
                    title = row.getString("summary")
                    val format = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ROOT)
                    start = requireNotNull(format.parse(row.getString("start"))).time
                    end = requireNotNull(format.parse(row.getString("end"))).time
                    showEvents = false; notice = ""; saveDraft()
                }) { Text(row.getString("summary") + "  " + row.getString("start").take(16).replace("T", " ")) } }
            }
            if (selectedEvent.isNotEmpty()) TextButton(onClick = {
                selectedEvent = ""; version = 0; title = ""; notice = ""; saveDraft()
            }, enabled = !busy) { Text("改为新增日程") }
        }
        if (agent) Box {
            OutlinedButton({ choosing = true }, enabled = !busy && chats.isNotEmpty()) {
                Text(chats[conversation] ?: if (chats.isEmpty()) "请先在电脑共享一个会话" else "选择已共享会话")
            }
            DropdownMenu(choosing, { choosing = false }) {
                chats.forEach { (id, name) -> DropdownMenuItem({ conversation = id; choosing = false; saveDraft() }) { Text(name) } }
            }
        } else OutlinedTextField(title, { title = it.take(120); saveDraft() },
            label = { Text("标题") }, singleLine = true, enabled = !busy, modifier = Modifier.fillMaxWidth())
        if (calendar) {
            val flags = DateUtils.FORMAT_SHOW_DATE or DateUtils.FORMAT_SHOW_TIME
            OutlinedButton({ pick(start) { start = it; if (end <= it) end = it + 1800000 } }, enabled = !busy) {
                Text("开始　" + DateUtils.formatDateTime(context, start, flags))
            }
            OutlinedButton({ pick(end) { end = it } }, enabled = !busy) {
                Text("结束　" + DateUtils.formatDateTime(context, end, flags))
            }
        } else OutlinedTextField(body, { body = it.take(4000); saveDraft() },
            label = { Text(if (agent) "想让伙伴做什么？" else "正文") }, enabled = !busy, modifier = Modifier.fillMaxWidth().heightIn(min = 140.dp))
        if (notice.isNotEmpty()) Text(notice)
        Button(enabled = !busy && device != null && (if (agent) conversation in chats else title.isNotBlank()) && (if (calendar) end > start else body.isNotBlank()),
            onClick = {
                val client = PairingClient.approved(context)
                if (client == null || client.pairedId != device || MobileAccount.owner != owner) {
                    notice = "配对已变化，草稿已保留"
                    return@Button
                }
                val format = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ROOT)
                val payload = if (agent) JSONObject().put("conversation", conversation).put("text", body) else if (calendar) JSONObject().put("summary", title).put("start", format.format(java.util.Date(start)))
                    .put("end", format.format(java.util.Date(end))) else JSONObject().put("title", title).put("body", body)
                val editEvent = calendar && selectedEvent.isNotEmpty()
                if (editEvent) payload.put("event", selectedEvent).put("version", version)
                val content = payload.toString()
                val id = prefs.getString("request", null)?.takeIf { prefs.getString("submitted", null) == content }
                    ?: UUID.randomUUID().toString()
                busy = true
                notice = "正在等待电脑回执"
                scope.launch {
                    try {
                        withContext(Dispatchers.IO) {
                            check(prefs.edit().putString("request", id).putString("submitted", content).commit())
                            client.create(if (editEvent) "calendar.update" else action, id, payload)
                        }
                        prefs.edit().clear().apply()
                        if (event != null) { back(); return@launch }
                        selectedEvent = ""; version = 0; title = ""; body = ""; notice = if (agent) "已提交到原会话" else "已保存到电脑"
                    } catch (e: CancellationException) { throw e }
                    catch (e: Exception) { notice = (e.message ?: "尚未收到回执") + " · 草稿已保留" }
                    finally { busy = false }
                }
            }) { Text(if (agent) "交给伙伴" else "保存到电脑") }
    }
}
