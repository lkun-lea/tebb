package dev.tebb.mobile

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

@Composable
private fun DialogTheme(content: @Composable () -> Unit) {
    val accent = Color(0xFF00A6F4)
    val colors = if (isSystemInDarkTheme()) {
        darkColors(primary = accent, surface = Color(0xFF1D1D1D), onSurface = Color(0xFFF1F1EF))
    } else {
        lightColors(primary = accent, surface = Color.White, onSurface = Color(0xFF253C4C))
    }
    MaterialTheme(colors = colors, content = content)
}

@Composable
internal fun WorkspaceAlertDialog(
    onDismissRequest: () -> Unit,
    title: @Composable () -> Unit,
    text: @Composable () -> Unit,
    confirmButton: @Composable () -> Unit,
    dismissButton: (@Composable () -> Unit)? = null
) {
    DialogTheme {
        AlertDialog(onDismissRequest = onDismissRequest, title = title, text = text,
            confirmButton = confirmButton, dismissButton = dismissButton, shape = RoundedCornerShape(18.dp))
    }
}

@Composable
internal fun WorkspaceDropdownMenu(
    expanded: Boolean,
    onDismissRequest: () -> Unit,
    content: @Composable ColumnScope.() -> Unit
) {
    DialogTheme {
        DropdownMenu(expanded = expanded, onDismissRequest = onDismissRequest, content = content)
    }
}
