package dev.tebb.mobile

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.ui.draw.scale
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.rotate
import androidx.compose.animation.core.*
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

private val Ink = Color(0xFF090909)
private val Paper = Color(0xFFF1F1EF)
private val Muted = Color(0xFFAAAAAA)
private val Accent = Color(0xFFBDCEA9)
private val Surface = Color(0xFF1D1D1D)

/** 组合 Android 主聊天和设备入口；只有展开面板属于 UI 临时状态，草稿和任务归属来自 [state]。 */
@Composable
internal fun ChatScreen(
    state: ChatUiState, device: PairingState, pairing: PairingViewModel,
    select: (QuestionKey) -> Unit, dismiss: () -> Unit, edit: (String) -> Unit,
    send: () -> Unit, voice: () -> Unit, stop: () -> Unit, cancel: () -> Unit,
    sync: (List<PendingQuestion>) -> Unit, retryHistory: () -> Unit, clearHistory: () -> Unit, chooseCloud: (Boolean) -> Unit
) {
    var sheet by rememberSaveable { mutableStateOf("") }
    var readingCode by remember { mutableStateOf(false) }
    val composer = state.composer
    val focus = LocalFocusManager.current
    var origin by remember { mutableStateOf(Offset.Zero) }
    var header by remember { mutableStateOf<Offset?>(null) }
    var welcome by remember { mutableStateOf<Offset?>(null) }
    val petQuestion = composer.target ?: composer.pending.firstOrNull()?.key
    var questionCenter by remember(petQuestion) { mutableStateOf<Offset?>(null) }
    val answerId = state.messages.lastOrNull { it.fromTebb }?.id
    var answerCenter by remember(answerId) { mutableStateOf<Offset?>(null) }
    val tasksOpen = sheet == "tasks"
    val loading = when {
        state.work != null -> state.work.label
        readingCode -> "正在识别配对码"
        device == PairingState.Connecting -> "正在连接电脑"
        else -> null
    }
    // 很快完成的本机读写直接更新内容，持续操作才显示思考反馈。
    var showLoading by remember(loading) { mutableStateOf(false) }
    LaunchedEffect(loading) {
        if (loading != null) {
            kotlinx.coroutines.delay(180)
            showLoading = true
        }
    }
    MaterialTheme(colors = darkColors(primary = Accent, background = Ink, surface = Surface, onSurface = Paper)) {
        Box(Modifier.fillMaxSize().background(Ink).imePadding().onGloballyPositioned { origin = it.positionInRoot() }) {
            Box(Modifier.fillMaxSize().blur(if (showLoading) 12.dp else 0.dp)) {
                // 读图协程由设备页面持有。显示加载层时让页面留在组合中，以便完成解码。
                if (sheet == "device") {
                    BackHandler(enabled = loading == null) { sheet = "" }
                    Column(Modifier.fillMaxSize().padding(20.dp)) {
                        TextButton(onClick = { sheet = "" }) { Text("返回聊天") }
                        Text("我的电脑", color = Paper, fontSize = 24.sp)
                        Spacer(Modifier.height(16.dp))
                        PairingPanel(pairing, onDecode = { readingCode = it })
                    }
                } else {
                    Column(Modifier.fillMaxSize()) {
                        Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            GlyphButton(if (tasksOpen) Glyph.Back else Glyph.Tasks, if (tasksOpen) "返回聊天" else "待答任务", {
                                if (!composer.dictating) {
                                    focus.clearFocus()
                                    sheet = if (tasksOpen) "" else "tasks"
                                }
                            })
                            if (!tasksOpen) Spacer(Modifier.width(48.dp))
                            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                                Box(Modifier.offset(x = (-52).dp)) { PetAnchor(40.dp) { header = it } }
                                Wordmark()
                            }
                            GlyphButton(Glyph.Device, (device as? PairingState.Paired)?.computer ?: "配对电脑", { if (!composer.dictating) sheet = "device" })
                            if (!tasksOpen) ChatHistoryMenu(state.messages.isNotEmpty(), !composer.dictating && loading == null, clearHistory)
                        }
                        Conversation(state, select, Modifier.weight(1f), petQuestion, { welcome = it }, { questionCenter = it },
                            answerId, { answerCenter = it }, { edit(it); send() })
                        (state.notice ?: state.connectionNotice)?.let { notice ->
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(notice, Modifier.weight(1f).padding(start = 16.dp), color = Accent)
                                if (state.historyReadFailed) TextButton(onClick = retryHistory) { Text("重试") }
                            }
                        }
                        ComposerBar(composer, state.listening, dismiss, edit, send, voice, stop, cancel) {
                            RuntimeMenu(state.cloud, composer.target != null, state.work == null && !composer.dictating, chooseCloud)
                        }
                    }
                    if (tasksOpen) {
                        Box(Modifier.fillMaxSize().padding(top = 56.dp)) {
                            TaskSheet(composer.pending, { select(it); sheet = "" }, { sheet = "" }, sync, device !is PairingState.Paired)
                        }
                    }
                    // 只有 tebb 提出的问题可以接住桌宠；本机发送记录全部属于用户。
                    val atQuestion = !tasksOpen && petQuestion != null && questionCenter != null
                    val atWelcome = !tasksOpen && composer.pending.isEmpty() && state.messages.isEmpty() && welcome != null
                    val atAnswer = !tasksOpen && !atQuestion && answerCenter != null
                    val center = when {
                        atAnswer -> answerCenter
                        atQuestion -> questionCenter
                        atWelcome -> welcome
                        else -> header
                    }
                    if (center != null && !showLoading) ChatPet(center - origin, if (atWelcome) 90.dp else 36.dp,
                        tasksOpen || composer.pending.isNotEmpty(), state.listening,
                        when { atAnswer -> "回答旁"; atQuestion -> "问题旁"; atWelcome -> "聊天中央"; else -> "顶部" }, pendingCount = composer.pending.size)
                }
            }
            if (loading != null && showLoading) {
                Dialog(
                    onDismissRequest = {},
                    properties = DialogProperties(usePlatformDefaultWidth = false, dismissOnClickOutside = false)
                ) { ThinkingOverlay(loading) }
            }
        }
    }
}

/** 在顶栏收纳历史操作；取消或按返回仅关闭弹窗，只有确认按钮会请求删除。 */
@Composable
private fun ChatHistoryMenu(hasMessages: Boolean, available: Boolean, clear: () -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    var confirming by rememberSaveable { mutableStateOf(false) }
    Box {
        GlyphButton(Glyph.More, "更多选项", { if (available) expanded = true })
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            DropdownMenuItem(enabled = hasMessages && available, onClick = {
                expanded = false
                confirming = true
            }) { Text("清空对话记录") }
        }
    }
    if (confirming) AlertDialog(
        onDismissRequest = { confirming = false },
        title = { Text("清空对话记录？") },
        text = { Text("这台设备上的全部聊天记录将被删除，无法恢复。草稿和待答任务会保留。") },
        dismissButton = { TextButton(onClick = { confirming = false }) { Text("取消") } },
        confirmButton = {
            TextButton(enabled = hasMessages && available, onClick = {
                confirming = false
                clear()
            }) { Text("清空", color = Color(0xFFFFABA3)) }
        }
    )
}

/** 居中的品牌字标与鼠尾草色句点，供聊天顶栏和全屏反馈共用。 */
@Composable
private fun Wordmark() {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("tebb", color = Paper, fontWeight = FontWeight.Bold, fontSize = 24.sp, letterSpacing = (-1).sp)
        Text(".", color = Accent, fontSize = 24.sp, fontWeight = FontWeight.Bold)
    }
}

/** 保留操作现场作为背景。桌宠轻轻歪头，视线来回移动，表示正在处理请求。 */
@Composable
private fun ThinkingOverlay(label: String) {
    val motion = rememberInfiniteTransition()
    val tilt by motion.animateFloat(-8f, 8f, infiniteRepeatable(tween(800), RepeatMode.Reverse))
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally) {
        Canvas(Modifier.size(72.dp).rotate(tilt)) {
            val u = size.width / 64f
            drawCircle(Color(0xFFD4CABA), 29.5f * u)
            drawCircle(Color(0xFFEEE9DC), 28f * u)
            for (x in listOf(21f, 36f)) drawRoundRect(Color(0xFF3E4443),
                Offset((x + tilt / 5) * u, 28 * u), Size(7 * u, 4 * u),
                androidx.compose.ui.geometry.CornerRadius(2 * u))
        }
        Spacer(Modifier.height(8.dp))
        Text(label, color = Paper, fontSize = 14.sp)
    }
}

/** 展示待答问题和本机消息。消息用稳定标识定位，新增消息后滚动到最新一条。 */
@Composable
private fun Conversation(state: ChatUiState, select: (QuestionKey) -> Unit, modifier: Modifier,
                         petQuestion: QuestionKey?, welcome: (Offset?) -> Unit, questionCenter: (Offset?) -> Unit,
                         answerId: Long?, answerCenter: (Offset?) -> Unit, startChat: (String) -> Unit) {
    val list = rememberLazyListState()
    val pending = state.composer.pending
    val demo = BuildConfig.DEBUG && pending.any { it in demoQuestions }
    val count = pending.size + state.messages.size + if (demo) 1 else 0
    LaunchedEffect(state.messages.lastOrNull()?.id) {
        if (state.messages.isNotEmpty()) list.scrollToItem(count - 1)
    }
    LazyColumn(modifier.fillMaxWidth(), state = list, contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)) {
        if (count == 0) item {
            Column(Modifier.fillParentMaxHeight().fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center) {
                PetAnchor(90.dp, welcome)
                Spacer(Modifier.height(20.dp))
                if (state.composer.draft.isBlank() && !state.composer.dictating) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        chatStarters.forEach { starter ->
                            TextButton(onClick = { startChat(starter) }) { Text(starter, color = Accent) }
                        }
                    }
                }
            }
        }
        if (demo) item {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(24.dp)) {
                Text("电脑上现在有什么事在等我？", Modifier.align(Alignment.End)
                    .background(Color(0xFF232325), RoundedCornerShape(22.dp, 22.dp, 7.dp, 22.dp))
                    .padding(horizontal = 16.dp, vertical = 10.dp), color = Paper)
                val summary = when (pending.singleOrNull()?.key?.runId) {
                    "demo-review" -> "周三的评审定在 14:00，还差会议时长。"
                    "demo-notes" -> "笔记已整理好，还需要确认资料来源。"
                    else -> "有两件事需要你确认。"
                }
                Text(summary,
                    color = Paper, fontSize = 17.sp, lineHeight = 26.sp)
            }
        }
        items(pending, key = { it.key }) { question ->
            Row(Modifier.fillMaxWidth().clickable { select(question.key) }.padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                if (question.key == petQuestion) {
                    PetAnchor(48.dp, questionCenter)
                }
                Spacer(Modifier.size(2.dp, 40.dp).background(Accent))
                Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                    Text(question.title, color = Accent, fontSize = 13.sp)
                    Text(question.prompt, color = Paper, fontSize = 17.sp, lineHeight = 26.sp)
                }
                Text("›", color = Muted, fontSize = 22.sp)
            }
        }
        items(state.messages, key = { it.id }) { message ->
            if (message.fromTebb) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    if (message.id == answerId) PetAnchor(48.dp, answerCenter)
                    Text(message.text, Modifier.widthIn(max = 310.dp)
                        .background(Surface, RoundedCornerShape(20.dp, 20.dp, 20.dp, 6.dp))
                        .padding(horizontal = 16.dp, vertical = 10.dp), color = Paper)
                }
                return@items
            }
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
                message.title?.let { Text("回复 · $it", color = Accent, fontSize = 12.sp) }
                Text(message.text, Modifier.widthIn(max = 310.dp)
                    .background(Color(0xFF232325), RoundedCornerShape(22.dp, 22.dp, 7.dp, 22.dp))
                    .padding(horizontal = 16.dp, vertical = 10.dp), color = Paper, fontSize = 16.sp, lineHeight = 24.sp)
                Text(if (message.windowsAccepted) "Windows 已接收" else "已保存到本机", color = Muted, fontSize = 12.sp)
            }
        }
    }
}

/** 共享文字和听写草稿。唯一引用显示在输入框上沿，关闭引用只改变回复目标。 */
@Composable
private fun ComposerBar(
    state: ComposerState, listening: Boolean, dismiss: () -> Unit, edit: (String) -> Unit,
    send: () -> Unit, voice: () -> Unit, stop: () -> Unit, cancel: () -> Unit, runtime: @Composable () -> Unit
) {
    val target = state.pending.firstOrNull { it.key == state.target }
    val shape = RoundedCornerShape(28.dp)
    val outline by animateColorAsState(if (listening) Accent.copy(alpha = .7f) else Color(0xFF363638))
    val hint = if (target == null) "给 tebb 发消息…" else "输入回答…"
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)
        .background(Brush.verticalGradient(listOf(Color(0xFF222224), Surface)), shape)
        .border(1.dp, outline, shape).padding(6.dp)) {
        if (target != null) Row(Modifier.fillMaxWidth().padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.size(2.dp, 14.dp).background(Accent, CircleShape))
            Text("正在回复 · ${target.title}", Modifier.weight(1f).padding(start = 8.dp),
                color = Accent, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (!state.dictating) GlyphButton(Glyph.Close, "取消任务引用", dismiss)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            BasicTextField(
                value = state.visibleDraft, onValueChange = edit, readOnly = state.dictating,
                modifier = Modifier.weight(1f).padding(horizontal = 12.dp, vertical = 8.dp).semantics { contentDescription = hint },
                maxLines = 5, textStyle = TextStyle(color = Paper, fontSize = 16.sp, lineHeight = 24.sp),
                cursorBrush = SolidColor(Accent), decorationBox = { inner ->
                    Box {
                        if (state.visibleDraft.isEmpty()) Text(if (listening) "正在听写…" else hint,
                            color = Muted, fontSize = 16.sp)
                        inner()
                    }
                }
            )
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            runtime()
            Spacer(Modifier.weight(1f))
            // 正文与临时候选共用输入框。录音钮固定在右端，手指按住期间不会因候选到达而被替换。
            if (!state.dictating && state.draft.isNotBlank()) GlyphButton(Glyph.Send, "发送", send)
            HoldToSpeak(listening, voice, stop, cancel)
        }
    }
}

/**
 * 手指按下即开始采音，抬起停止；系统取消手势时撤销本轮。回调更新不会重启进行中的触摸监听。
 * 读屏用户可通过同一控件分别执行开始与停止动作。
 */
@Composable
private fun HoldToSpeak(listening: Boolean, start: () -> Unit, stop: () -> Unit, cancel: () -> Unit) {
    val startNow by rememberUpdatedState(start)
    val stopNow by rememberUpdatedState(stop)
    val cancelNow by rememberUpdatedState(cancel)
    val active by rememberUpdatedState(listening)
    val face by animateColorAsState(if (listening) Accent else Paper)
    val scale by animateFloatAsState(if (listening) .93f else 1f)
    Box(Modifier.size(48.dp).semantics {
        contentDescription = if (listening) "松开停止听写" else "按住说话"
        role = Role.Button
        onClick(label = if (listening) "停止听写" else "开始听写") {
            if (active) stopNow() else startNow()
            true
        }
    }.pointerInput(Unit) {
        detectTapGestures(onPress = {
            startNow()
            try {
                if (tryAwaitRelease()) stopNow() else if (active) cancelNow()
            } catch (e: kotlinx.coroutines.CancellationException) {
                if (active) cancelNow()
                throw e
            }
        })
    }, contentAlignment = Alignment.Center) {
        Box(Modifier.size(44.dp).scale(scale).background(face, CircleShape), contentAlignment = Alignment.Center) {
            Canvas(Modifier.size(24.dp)) {
                val unit = size.width / 24f
                listOf(3, 6, 9, 5, 3).forEachIndexed { i, half ->
                    val x = (4 + 4 * i) * unit
                    drawLine(Ink, Offset(x, (12 - half) * unit), Offset(x, (12 + half) * unit),
                        2.2f * unit, cap = StrokeCap.Round)
                }
            }
        }
    }
}

/** 显示按问题版本选择的待答清单；调试包允许切换示例快照以验证刷新与取消行为。 */
@Composable
private fun TaskSheet(questions: List<PendingQuestion>, select: (QuestionKey) -> Unit,
                      close: () -> Unit, sync: (List<PendingQuestion>) -> Unit, allowDemo: Boolean) {
    BackHandler(onBack = close)
    Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.65f)).clickable(onClick = close),
        contentAlignment = Alignment.BottomCenter) {
        Surface(shape = RoundedCornerShape(topStart = 22.dp, topEnd = 22.dp), color = Surface) {
            Column(Modifier.fillMaxWidth().clickable(enabled = false) {}.padding(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("待答任务", Modifier.weight(1f).semantics { heading() }, color = Paper, fontSize = 20.sp)
                    GlyphButton(Glyph.Close, "关闭待答任务", close)
                }
                if (questions.isEmpty()) Text("目前没有待答问题", color = Muted)
                LazyColumn(Modifier.heightIn(max = 280.dp)) {
                    items(questions, key = { it.key }) { question ->
                        Column(Modifier.fillMaxWidth().clickable { select(question.key) }.padding(vertical = 10.dp)) {
                            Text(question.title, color = Accent)
                            Text(question.prompt, color = Paper)
                        }
                    }
                }
                if (BuildConfig.DEBUG && allowDemo) {
                    Text("调试 · 本地待答快照", color = Muted, fontSize = 12.sp)
                    Row { listOf("无待答", "单个", "多个").forEachIndexed { count, label ->
                        TextButton(onClick = { sync(demoQuestions.take(count)); close() }) { Text(label) }
                    } }
                }
            }
        }
    }
}

/** 聊天中的线性图标由 Canvas 绘制，图形与点击区域独立缩放。 */
private enum class Glyph { More, Back, Tasks, Device, Close, Send }

/** 绘制 24dp 图形并提供 48dp 触摸区域，[label] 供读屏软件描述按钮动作。 */
@Composable
private fun GlyphButton(glyph: Glyph, label: String, click: () -> Unit, filled: Boolean = false) {
    val color = if (filled) Ink else Paper
    IconButton(onClick = click, modifier = Modifier.size(48.dp).clip(CircleShape)
        .background(if (filled) Paper else Color.Transparent).semantics { contentDescription = label }) {
        Canvas(Modifier.size(24.dp)) {
            val unit = size.width / 24f
            fun line(x: Int, y: Int, endX: Int, endY: Int) = drawLine(color,
                Offset(x * unit, y * unit), Offset(endX * unit, endY * unit), 1.8f * unit)
            when (glyph) {
                Glyph.Back -> { line(4, 12, 20, 12); line(4, 12, 11, 5); line(4, 12, 11, 19) }
                Glyph.Tasks -> { line(3, 8, 20, 8); line(3, 15, 14, 15) }
                Glyph.More -> for (y in listOf(5, 12, 19)) drawCircle(color, 1.7f * unit, Offset(12 * unit, y * unit))
                Glyph.Device -> { drawRect(color, Offset(4*unit, 5*unit), Size(16*unit, 12*unit), style = Stroke(1.6f*unit)); line(2, 20, 22, 20) }
                Glyph.Close -> { line(6, 6, 18, 18); line(18, 6, 6, 18) }
                Glyph.Send -> { line(12, 20, 12, 4); line(5, 11, 12, 4); line(12, 4, 19, 11) }
            }
        }
    }
}

/**
 * 显示普通消息的执行位置。选择后由 [choose] 更新偏好，菜单随即收起。
 * 引用任务时临时锁定到原 Windows，取消引用后恢复原偏好；听写和发送期间暂停切换。
 */
@Composable
private fun RuntimeMenu(cloud: Boolean, locked: Boolean, idle: Boolean, choose: (Boolean) -> Unit) {
    var open by remember(locked, idle) { mutableStateOf(false) }
    val label = when {
        locked -> "Windows · 原任务"
        cloud -> "云端"
        else -> "本地"
    }
    Box(Modifier.padding(start = 4.dp)) {
        TextButton(
            onClick = { open = true }, enabled = idle && !locked,
            modifier = Modifier.heightIn(min = 48.dp).semantics {
                contentDescription = "执行位置"
                stateDescription = if (locked) "已锁定到 Windows 原任务" else label
            },
            shape = RoundedCornerShape(18.dp),
            colors = ButtonDefaults.textButtonColors(contentColor = Accent, disabledContentColor = Muted)
        ) {
            Text(label, fontSize = 14.sp)
            if (!locked) Icon(Icons.Filled.ArrowDropDown, contentDescription = null, modifier = Modifier.size(18.dp))
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            listOf(false to "本地", true to "云端 · 免费 Qwen").forEach { (value, name) ->
                val selected = cloud == value
                DropdownMenuItem(onClick = { open = false; choose(value) },
                    modifier = Modifier.semantics { stateDescription = if (selected) "已选中" else "未选中" }) {
                    Text(name, Modifier.weight(1f), color = if (selected) Accent else Paper)
                    if (selected) Text("✓", color = Accent)
                }
            }
        }
    }
}
