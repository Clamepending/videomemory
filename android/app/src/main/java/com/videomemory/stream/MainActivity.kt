package com.videomemory.stream

import android.Manifest
import android.content.res.Configuration
import android.net.Uri
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.SurfaceHolder
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatDelegate
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.widget.doAfterTextChanged
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.pedro.common.ConnectChecker
import com.pedro.library.rtmp.RtmpStream
import com.videomemory.stream.databinding.ActivityMainBinding
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class MainActivity : AppCompatActivity(), ConnectChecker {

    private lateinit var binding: ActivityMainBinding
    private var rtmpStream: RtmpStream? = null
    private var streaming = false
    private var starting = false
    private var eventMode = false
    private var pendingStartUrl: String? = null
    private var eventFetchInFlight = false
    private val uiHandler = Handler(Looper.getMainLooper())
    private val eventTimeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault())
    private val eventPollRunnable = object : Runnable {
        override fun run() {
            if (!eventMode) return
            loadEvents()
            uiHandler.postDelayed(this, EVENT_POLL_INTERVAL_MS)
        }
    }
    private val qrScanner: GmsBarcodeScanner by lazy {
        val options = GmsBarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .enableAutoZoom()
            .build()
        GmsBarcodeScanning.getClient(this, options)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        requestPermissions()
        binding.preview.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(h: SurfaceHolder) {
                startPendingStreamIfReady()
            }
            override fun surfaceChanged(h: SurfaceHolder, format: Int, width: Int, height: Int) {
                startPendingStreamIfReady()
            }
            override fun surfaceDestroyed(h: SurfaceHolder) {}
        })
        binding.btnStart.setOnClickListener { startStream() }
        binding.btnStop.setOnClickListener { stopStream() }
        binding.btnScanQr.setOnClickListener { scanQrCode() }
        binding.btnScanEventQr.setOnClickListener { scanEventQrCode() }
        binding.btnRefreshEvents.setOnClickListener { loadEvents() }
        binding.themeToggleButton.setOnClickListener { toggleThemeMode() }
        binding.modeToggleGroup.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked) return@addOnButtonCheckedListener
            val newEventMode = checkedId == R.id.btnModeEvent
            if (newEventMode == eventMode) return@addOnButtonCheckedListener
            if (newEventMode && (streaming || starting)) {
                stopStream()
            }
            eventMode = newEventMode
            if (eventMode) {
                ensureEventBaseUrl()
                loadEvents()
                startEventPolling()
            } else {
                stopEventPolling()
            }
            renderStreamingState()
        }
        binding.urlInput.doAfterTextChanged { renderStreamingState() }
        updateThemeToggleIcon()
        renderStreamingState()
    }

    override fun onResume() {
        super.onResume()
        updateThemeToggleIcon()
        if (eventMode) {
            startEventPolling()
        }
    }

    override fun onPause() {
        stopEventPolling()
        super.onPause()
    }

    private fun requestPermissions() {
        val perms = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (perms.any { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }) {
            ActivityCompat.requestPermissions(this, perms, 0)
        }
    }

    private fun startStream() {
        if (eventMode) return
        if (streaming || starting) return
        val url = binding.urlInput.text.toString().trim()
        if (url.isBlank()) {
            Toast.makeText(this, "Enter RTMP URL", Toast.LENGTH_SHORT).show()
            return
        }
        if (!isSupportedRtmpUrl(url)) {
            Toast.makeText(this, "URL must start with rtmp:// or rtmps://", Toast.LENGTH_SHORT).show()
            return
        }
        if (rtmpStream == null) {
            rtmpStream = RtmpStream(this, this)
            val ok = rtmpStream!!.prepareVideo(
                width = 1280,
                height = 720,
                bitrate = 1_200_000,
                rotation = 90
            ) &&
                rtmpStream!!.prepareAudio(48000, true, 128 * 1024)
            if (!ok) {
                Toast.makeText(this, "Prepare failed", Toast.LENGTH_SHORT).show()
                rtmpStream = null
                return
            }
        }
        pendingStartUrl = url
        starting = true
        renderStreamingState()
        startPendingStreamIfReady()
    }

    private fun stopStream() {
        pendingStartUrl = null
        starting = false
        rtmpStream?.stopStream()
        rtmpStream?.stopPreview()
        streaming = false
        renderStreamingState()
    }

    private fun scanQrCode() {
        if (eventMode) return
        if (streaming || starting) return
        qrScanner.startScan()
            .addOnSuccessListener { barcode ->
                val raw = barcode.rawValue?.trim().orEmpty()
                val rtmpUrl = extractRtmpUrl(raw)
                if (rtmpUrl == null) {
                    Toast.makeText(this, getString(R.string.scan_qr_invalid), Toast.LENGTH_SHORT).show()
                    return@addOnSuccessListener
                }
                binding.urlInput.setText(rtmpUrl)
                binding.urlInput.setSelection(rtmpUrl.length)
                Toast.makeText(this, getString(R.string.scan_qr_success), Toast.LENGTH_SHORT).show()
            }
            .addOnFailureListener { error ->
                Log.e(TAG, "QR scan failed", error)
                Toast.makeText(this, getString(R.string.scan_qr_error), Toast.LENGTH_SHORT).show()
            }
    }

    private fun scanEventQrCode() {
        if (!eventMode) return
        if (streaming || starting) return
        qrScanner.startScan()
            .addOnSuccessListener { barcode ->
                val raw = barcode.rawValue?.trim().orEmpty()
                val baseUrl = extractEventBaseUrl(raw)
                if (baseUrl == null) {
                    Toast.makeText(this, getString(R.string.scan_event_qr_invalid), Toast.LENGTH_SHORT).show()
                    return@addOnSuccessListener
                }
                binding.eventsBaseUrlInput.setText(baseUrl)
                binding.eventsBaseUrlInput.setSelection(baseUrl.length)
                Toast.makeText(this, getString(R.string.scan_event_qr_success), Toast.LENGTH_SHORT).show()
                loadEvents()
            }
            .addOnFailureListener { error ->
                Log.e(TAG, "Event QR scan failed", error)
                Toast.makeText(this, getString(R.string.scan_qr_error), Toast.LENGTH_SHORT).show()
            }
    }

    override fun onConnectionStarted(url: String) {}
    override fun onConnectionSuccess() {
        runOnUiThread { Toast.makeText(this, "Connected", Toast.LENGTH_SHORT).show() }
    }
    override fun onConnectionFailed(reason: String) {
        Log.e(TAG, "Connection failed: $reason")
        runOnUiThread {
            Toast.makeText(this, "Failed: $reason", Toast.LENGTH_LONG).show()
            stopStream()
        }
    }
    override fun onDisconnect() {
        runOnUiThread { if (streaming) stopStream() }
    }
    override fun onAuthError() {
        runOnUiThread { Toast.makeText(this, "Auth error", Toast.LENGTH_SHORT).show() }
    }
    override fun onAuthSuccess() {}
    override fun onNewBitrate(bitrate: Long) {}

    override fun onDestroy() {
        stopEventPolling()
        rtmpStream?.release()
        rtmpStream = null
        super.onDestroy()
    }

    private fun extractRtmpUrl(raw: String): String? {
        if (raw.isBlank()) return null
        val embedded = Regex("""rtmps?://\S+""", RegexOption.IGNORE_CASE).find(raw)?.value ?: raw
        val cleaned = embedded.trim().trimEnd('.', ',', ';', ')', ']')
        return if (
            cleaned.startsWith("rtmp://", ignoreCase = true) ||
            cleaned.startsWith("rtmps://", ignoreCase = true)
        ) {
            cleaned
        } else {
            null
        }
    }

    private fun extractEventBaseUrl(raw: String): String? {
        if (raw.isBlank()) return null
        val embedded = Regex("""https?://\S+""", RegexOption.IGNORE_CASE).find(raw)?.value ?: raw
        var cleaned = embedded.trim().trimEnd('.', ',', ';', ')', ']')
        if (!cleaned.startsWith("http://", ignoreCase = true) &&
            !cleaned.startsWith("https://", ignoreCase = true)
        ) {
            return null
        }
        val endpointPattern = Regex("""/api/mcp/events/?$""", RegexOption.IGNORE_CASE)
        cleaned = cleaned.replace(endpointPattern, "")
        return normalizeApiBaseUrl(cleaned)
    }

    private fun renderStreamingState() {
        val streamingMode = !eventMode
        val active = streaming || starting
        val hasUrl = !binding.urlInput.text.isNullOrBlank()
        val checkedModeId = if (streamingMode) R.id.btnModeStreaming else R.id.btnModeEvent
        if (binding.modeToggleGroup.checkedButtonId != checkedModeId) {
            binding.modeToggleGroup.check(checkedModeId)
        }
        binding.streamingModeContent.visibility = if (streamingMode) View.VISIBLE else View.GONE
        binding.eventModeContent.visibility = if (streamingMode) View.GONE else View.VISIBLE
        binding.streamControlsRow.visibility = if (streamingMode && (hasUrl || active)) View.VISIBLE else View.GONE
        binding.btnStart.visibility = if (streamingMode && !active) View.VISIBLE else View.GONE
        binding.btnStop.visibility = if (streamingMode && active) View.VISIBLE else View.GONE
        binding.previewCard.visibility = if (streamingMode && active) View.VISIBLE else View.GONE
        binding.btnStart.isEnabled = streamingMode && !active && hasUrl
        binding.btnStop.isEnabled = streamingMode && active
        binding.urlInput.isEnabled = streamingMode && !active
        binding.btnScanQr.isEnabled = streamingMode && !active
        binding.btnScanEventQr.isEnabled = !streamingMode && !active
        if (streamingMode) {
            if (active) {
                binding.statusText.text = getString(R.string.status_streaming)
                binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_live_text))
                binding.statusText.setBackgroundResource(R.drawable.status_pill_live)
            } else {
                binding.statusText.text = getString(R.string.status_idle)
                binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_idle_text))
                binding.statusText.setBackgroundResource(R.drawable.status_pill_idle)
            }
        }
    }

    private fun isSupportedRtmpUrl(url: String): Boolean {
        return url.startsWith("rtmp://", ignoreCase = true) ||
            url.startsWith("rtmps://", ignoreCase = true)
    }

    private fun toggleThemeMode() {
        val enableDarkMode = !isDarkModeActive()
        val newMode = if (enableDarkMode) {
            AppCompatDelegate.MODE_NIGHT_YES
        } else {
            AppCompatDelegate.MODE_NIGHT_NO
        }
        ThemeSettings.saveThemeMode(this, newMode)
        AppCompatDelegate.setDefaultNightMode(newMode)
    }

    private fun isDarkModeActive(): Boolean {
        val currentNightMode = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK
        return currentNightMode == Configuration.UI_MODE_NIGHT_YES
    }

    private fun updateThemeToggleIcon() {
        val darkModeActive = isDarkModeActive()
        binding.themeToggleButton.setImageResource(
            if (darkModeActive) R.drawable.ic_light_mode_24 else R.drawable.ic_dark_mode_24
        )
        binding.themeToggleButton.contentDescription = getString(
            if (darkModeActive) R.string.theme_switch_to_light else R.string.theme_switch_to_dark
        )
    }

    private fun ensureEventBaseUrl() {
        if (!binding.eventsBaseUrlInput.text.isNullOrBlank()) return
        val candidate = deriveApiBaseUrlFromRtmp(binding.urlInput.text?.toString().orEmpty())
            ?: DEFAULT_API_BASE_URL
        binding.eventsBaseUrlInput.setText(candidate)
        binding.eventsBaseUrlInput.setSelection(candidate.length)
    }

    private fun deriveApiBaseUrlFromRtmp(rtmpUrl: String): String? {
        val raw = rtmpUrl.trim()
        if (raw.isBlank()) return null
        return try {
            val parsed = Uri.parse(raw)
            val host = parsed.host?.trim().orEmpty()
            if (host.isBlank()) {
                null
            } else {
                "http://$host:$DEFAULT_API_PORT"
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun normalizeApiBaseUrl(raw: String): String? {
        var base = raw.trim()
        if (base.isBlank()) return null
        if (!base.startsWith("http://", ignoreCase = true) &&
            !base.startsWith("https://", ignoreCase = true)
        ) {
            base = "http://$base"
        }
        return base.trimEnd('/')
    }

    private fun startEventPolling() {
        stopEventPolling()
        uiHandler.postDelayed(eventPollRunnable, EVENT_POLL_INTERVAL_MS)
    }

    private fun stopEventPolling() {
        uiHandler.removeCallbacks(eventPollRunnable)
    }

    private fun loadEvents() {
        if (!eventMode || eventFetchInFlight) return
        val baseUrl = normalizeApiBaseUrl(binding.eventsBaseUrlInput.text?.toString().orEmpty())
        if (baseUrl == null) {
            binding.eventStatusText.text = getString(
                R.string.event_status_error,
                getString(R.string.hint_event_backend)
            )
            return
        }
        binding.eventStatusText.text = getString(R.string.event_status_loading)
        val url = "$baseUrl/api/mcp/events?limit=$EVENT_FETCH_LIMIT"
        eventFetchInFlight = true
        Thread {
            val result = runCatching { fetchEvents(url) }
            runOnUiThread {
                eventFetchInFlight = false
                if (!eventMode) return@runOnUiThread
                result
                    .onSuccess { payload ->
                        val output = if (payload.lines.isEmpty()) {
                            getString(R.string.event_log_empty)
                        } else {
                            payload.lines.joinToString("\n\n")
                        }
                        binding.eventLogText.text = output
                        binding.eventStatusText.text = getString(
                            R.string.event_status_updated,
                            nowTimeText(),
                            payload.count
                        )
                        if (!payload.warning.isNullOrBlank()) {
                            binding.eventStatusText.append(
                                "\n" + getString(R.string.event_status_warning, payload.warning)
                            )
                        }
                    }
                    .onFailure { error ->
                        binding.eventStatusText.text = getString(
                            R.string.event_status_error,
                            compactText(error.message ?: error.javaClass.simpleName, 120)
                        )
                    }
            }
        }.start()
    }

    private fun fetchEvents(url: String): EventFetchPayload {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 2500
            readTimeout = 2500
            setRequestProperty("Accept", "application/json")
        }
        try {
            val code = conn.responseCode
            val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()
                ?.use { it.readText() }
                .orEmpty()
            if (code !in 200..299) {
                throw IOException(extractHttpError(code, body))
            }
            return parseEventsPayload(body)
        } finally {
            conn.disconnect()
        }
    }

    private fun extractHttpError(statusCode: Int, body: String): String {
        if (body.isBlank()) return "HTTP $statusCode"
        return try {
            val json = JSONObject(body)
            val detail = json.optString("error").ifBlank { json.optString("message") }
            if (detail.isBlank()) "HTTP $statusCode" else "HTTP $statusCode: $detail"
        } catch (_: Exception) {
            "HTTP $statusCode: ${compactText(body, 120)}"
        }
    }

    private fun parseEventsPayload(body: String): EventFetchPayload {
        val json = JSONObject(body)
        val warning = json.optString("warning").trim().ifBlank { null }
        val events = json.optJSONArray("events")
        val count = json.optInt("count", events?.length() ?: 0)
        if (events == null || events.length() == 0) {
            return EventFetchPayload(emptyList(), count, warning)
        }
        val lines = mutableListOf<String>()
        val start = maxOf(0, events.length() - EVENT_RENDER_LIMIT)
        for (i in start until events.length()) {
            val item = events.opt(i)
            if (item is JSONObject) {
                lines += formatEventLine(item)
            } else {
                lines += compactText(item?.toString().orEmpty(), 200)
            }
        }
        return EventFetchPayload(lines, count, warning)
    }

    private fun formatEventLine(event: JSONObject): String {
        val ts = event.optDouble("ts", Double.NaN)
        val timeText = if (ts.isNaN()) {
            "--:--:--"
        } else {
            eventTimeFormatter.format(Instant.ofEpochMilli((ts * 1000.0).toLong()))
        }
        val seq = event.opt("seq")?.toString()?.takeIf { it.isNotBlank() } ?: "-"
        val source = event.optString("event_source").ifBlank { "event" }
        val method = event.optString("method").ifBlank { "unknown" }
        val status = event.optString("status").ifBlank { "ok" }
        val summary = firstNonBlank(
            event.optString("result_summary"),
            event.optString("result_error"),
            event.optString("error")
        )
        return if (summary.isBlank()) {
            "[$timeText] $seq $source/$method $status"
        } else {
            "[$timeText] $seq $source/$method $status\n${compactText(summary, 220)}"
        }
    }

    private fun firstNonBlank(vararg values: String): String {
        for (value in values) {
            if (value.isNotBlank() && value != "null") return value
        }
        return ""
    }

    private fun compactText(value: String, maxLen: Int): String {
        val singleLine = value.replace(Regex("\\s+"), " ").trim()
        if (singleLine.length <= maxLen) return singleLine
        return singleLine.take(maxLen - 3) + "..."
    }

    private fun nowTimeText(): String {
        return eventTimeFormatter.format(Instant.now())
    }

    private fun startPendingStreamIfReady() {
        if (!starting || streaming) return
        if (!binding.preview.holder.surface.isValid) return
        val url = pendingStartUrl ?: return
        val stream = rtmpStream ?: return
        try {
            stream.startPreview(binding.preview)
            stream.startStream(url)
            streaming = true
            starting = false
            pendingStartUrl = null
            renderStreamingState()
        } catch (e: IllegalArgumentException) {
            // Surface validity can race with rendering; retry shortly.
            Log.w(TAG, "Preview surface not ready yet", e)
            binding.preview.postDelayed({ startPendingStreamIfReady() }, 120L)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start stream", e)
            starting = false
            pendingStartUrl = null
            renderStreamingState()
            Toast.makeText(this, "Failed to start stream", Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        private const val TAG = "VideoMemoryStream"
        private const val EVENT_POLL_INTERVAL_MS = 3000L
        private const val EVENT_FETCH_LIMIT = 200
        private const val EVENT_RENDER_LIMIT = 30
        private const val DEFAULT_API_PORT = 5050
        private const val DEFAULT_API_BASE_URL = "http://127.0.0.1:5050"
    }
}

private data class EventFetchPayload(
    val lines: List<String>,
    val count: Int,
    val warning: String?
)
