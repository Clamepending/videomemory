package com.videomemory.stream

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.SurfaceHolder
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.pedro.common.AudioCodec
import com.pedro.common.ConnectChecker
import com.pedro.common.VideoCodec
import com.pedro.library.rtmp.RtmpStream
import com.videomemory.stream.databinding.ActivityMainBinding
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity(), ConnectChecker {

    private lateinit var binding: ActivityMainBinding
    private var rtmpStream: RtmpStream? = null
    private var running = false
    private var appMode = AppMode.STREAMING
    private var eventExecutor: ScheduledExecutorService? = null
    private var eventSequence: Long = 0
    private val eventLogLines = ArrayDeque<String>()
    private val edgeStateLock = Any()
    private val edgeTasks = mutableListOf<EdgeTask>()
    private var nextEdgeTaskId = 1

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        loadModePreference()
        renderModeUi()
        prefillDestination()
        prefillEventToken()
        requestPermissions()
        binding.preview.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(h: SurfaceHolder) {}
            override fun surfaceChanged(h: SurfaceHolder, format: Int, width: Int, height: Int) {}
            override fun surfaceDestroyed(h: SurfaceHolder) {}
        })
        binding.modeToggle.addOnButtonCheckedListener { _, checkedId, isChecked ->
            if (!isChecked || running) return@addOnButtonCheckedListener
            val nextMode = if (checkedId == binding.btnModeEvent.id) AppMode.EVENT else AppMode.STREAMING
            if (appMode != nextMode) {
                appMode = nextMode
                saveModePreference()
                renderModeUi()
                prefillDestination()
                renderRunningState()
            }
        }
        binding.btnStart.setOnClickListener {
            if (running) stopCurrentMode() else startCurrentMode()
        }
        binding.btnEmitTestEvent.setOnClickListener {
            if (appMode == AppMode.EVENT && running) {
                sendEventAsync(manual = true)
            }
        }
        initEdgeServerDemoState()
        appendEventLog("App ready in ${appMode.prefValue} mode")
        renderRunningState()
        renderEdgeState()
    }

    private fun requestPermissions() {
        val perms = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (perms.any { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }) {
            ActivityCompat.requestPermissions(this, perms, 0)
        }
    }

    private fun startCurrentMode() {
        when (appMode) {
            AppMode.STREAMING -> startStreamingMode()
            AppMode.EVENT -> startEventMode()
        }
    }

    private fun startStreamingMode() {
        val url = binding.urlInput.text.toString().trim()
        if (url.isBlank()) {
            Toast.makeText(this, "Enter RTMP URL", Toast.LENGTH_SHORT).show()
            return
        }
        if (!url.startsWith("rtmp://", ignoreCase = true)) {
            Toast.makeText(this, "URL must start with rtmp://", Toast.LENGTH_SHORT).show()
            return
        }
        if (!ensurePreparedStream()) return
        saveDestination(url)
        saveEventTokenIfApplicable()
        rtmpStream!!.startPreview(binding.preview)
        rtmpStream!!.startStream(url)
        running = true
        renderRunningState()
    }

    private fun startEventMode() {
        val url = binding.urlInput.text.toString().trim()
        if (url.isBlank()) {
            Toast.makeText(this, "Enter event endpoint URL", Toast.LENGTH_SHORT).show()
            return
        }
        if (!(url.startsWith("http://", ignoreCase = true) || url.startsWith("https://", ignoreCase = true))) {
            Toast.makeText(this, "Event URL must start with http:// or https://", Toast.LENGTH_SHORT).show()
            return
        }
        if (!ensurePreparedStream()) return
        saveDestination(url)
        saveEventTokenIfApplicable()
        rtmpStream!!.startPreview(binding.preview)
        startEventLoop(url)
        running = true
        renderRunningState()
        appendEventLog("Event Mode started -> $url")
        renderEdgeState()
        sendEventAsync(manual = false)
    }

    private fun stopCurrentMode() {
        eventExecutor?.shutdownNow()
        eventExecutor = null
        try {
            rtmpStream?.stopStream()
        } catch (_: Exception) {
        }
        rtmpStream?.stopPreview()
        running = false
        appendEventLog("Stopped ${appMode.prefValue} mode")
        renderRunningState()
    }

    override fun onConnectionStarted(url: String) {}
    override fun onConnectionSuccess() {
        runOnUiThread { Toast.makeText(this, "Connected", Toast.LENGTH_SHORT).show() }
    }
    override fun onConnectionFailed(reason: String) {
        Log.e(TAG, "Connection failed: $reason")
        runOnUiThread {
            Toast.makeText(this, "Failed: $reason", Toast.LENGTH_LONG).show()
            stopCurrentMode()
        }
    }
    override fun onDisconnect() {
        runOnUiThread { if (running && appMode == AppMode.STREAMING) stopCurrentMode() }
    }
    override fun onAuthError() {
        runOnUiThread { Toast.makeText(this, "Auth error", Toast.LENGTH_SHORT).show() }
    }
    override fun onAuthSuccess() {}
    override fun onNewBitrate(bitrate: Long) {}

    override fun onDestroy() {
        eventExecutor?.shutdownNow()
        eventExecutor = null
        rtmpStream?.release()
        rtmpStream = null
        super.onDestroy()
    }

    private fun prefillDestination() {
        if (!binding.urlInput.text.isNullOrBlank()) return
        val saved = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            .getString(if (appMode == AppMode.EVENT) KEY_LAST_EVENT_URL else KEY_LAST_RTMP_URL, null)
            ?.trim()
        val fallback = if (appMode == AppMode.EVENT) getString(R.string.default_event_url) else getString(R.string.default_rtmp_url)
        val initialValue = if (saved.isNullOrBlank()) fallback else saved
        binding.urlInput.setText(initialValue)
        binding.urlInput.setSelection(initialValue.length)
    }

    private fun saveDestination(url: String) {
        val key = if (appMode == AppMode.EVENT) KEY_LAST_EVENT_URL else KEY_LAST_RTMP_URL
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit().putString(key, url).apply()
    }

    private fun prefillEventToken() {
        val saved = getSharedPreferences(PREFS_NAME, MODE_PRIVATE).getString(KEY_EVENT_TOKEN, "") ?: ""
        binding.tokenInput.setText(saved)
    }

    private fun saveEventTokenIfApplicable() {
        if (appMode != AppMode.EVENT) return
        val token = binding.tokenInput.text?.toString()?.trim().orEmpty()
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit().putString(KEY_EVENT_TOKEN, token).apply()
    }

    private fun renderRunningState() {
        binding.btnStart.isEnabled = true
        binding.btnStart.text = getString(if (running) R.string.stop else R.string.start)
        binding.btnStart.backgroundTintList =
            ContextCompat.getColorStateList(this, if (running) R.color.button_stop else R.color.button_primary)
        binding.urlInput.isEnabled = !running
        binding.tokenInput.isEnabled = !running
        binding.modeToggle.isEnabled = !running
        binding.btnModeStreaming.isEnabled = !running
        binding.btnModeEvent.isEnabled = !running
        binding.btnEmitTestEvent.visibility = if (appMode == AppMode.EVENT && running) android.view.View.VISIBLE else android.view.View.GONE
        val showEventWidgets = appMode == AppMode.EVENT
        binding.eventLogLabel.visibility = if (showEventWidgets) android.view.View.VISIBLE else android.view.View.GONE
        binding.eventLogText.visibility = if (showEventWidgets) android.view.View.VISIBLE else android.view.View.GONE
        binding.tokenInputLayout.visibility = if (showEventWidgets) android.view.View.VISIBLE else android.view.View.GONE
        binding.edgeStateLabel.visibility = if (showEventWidgets) android.view.View.VISIBLE else android.view.View.GONE
        binding.edgeStateText.visibility = if (showEventWidgets) android.view.View.VISIBLE else android.view.View.GONE
        if (running) {
            binding.statusText.text = if (appMode == AppMode.EVENT) getString(R.string.status_event_active) else getString(R.string.status_streaming)
            binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_live_text))
            binding.statusText.setBackgroundResource(R.drawable.status_pill_live)
        } else {
            binding.statusText.text = getString(R.string.status_idle)
            binding.statusText.setTextColor(ContextCompat.getColor(this, R.color.status_idle_text))
            binding.statusText.setBackgroundResource(R.drawable.status_pill_idle)
        }
    }

    private fun renderModeUi() {
        if (appMode == AppMode.EVENT) {
            binding.modeToggle.check(binding.btnModeEvent.id)
            binding.destinationLabel.text = getString(R.string.event_destination)
            binding.urlInputLayout.hint = getString(R.string.hint_event_url)
            binding.modeHelpText.text = getString(R.string.mode_help_event)
            appendEventLog("Switched to event mode")
        } else {
            binding.modeToggle.check(binding.btnModeStreaming.id)
            binding.destinationLabel.text = getString(R.string.rtmp_destination)
            binding.urlInputLayout.hint = getString(R.string.hint_rtmp_url)
            binding.modeHelpText.text = getString(R.string.mode_help_streaming)
            appendEventLog("Switched to streaming mode")
        }
        binding.urlInput.text?.clear()
    }

    private fun loadModePreference() {
        val saved = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            .getString(KEY_APP_MODE, AppMode.STREAMING.prefValue)
            ?.trim()
            ?.lowercase()
        appMode = if (saved == AppMode.EVENT.prefValue) AppMode.EVENT else AppMode.STREAMING
    }

    private fun saveModePreference() {
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
            .edit()
            .putString(KEY_APP_MODE, appMode.prefValue)
            .apply()
    }

    private fun ensurePreparedStream(): Boolean {
        if (rtmpStream == null) {
            rtmpStream = RtmpStream(this, this)
        }
        val ok = try {
            // Force RTMP-compatible codecs so MediaMTX doesn't reject codec negotiation.
            rtmpStream!!.setVideoCodec(VideoCodec.H264)
            rtmpStream!!.setAudioCodec(AudioCodec.AAC)
            rtmpStream!!.prepareVideo(
                width = 1280,
                height = 720,
                bitrate = 1_200_000,
                fps = 30,
                iFrameInterval = 2,
                rotation = 90
            ) && rtmpStream!!.prepareAudio(48000, true, 128 * 1024)
        } catch (e: Exception) {
            Log.e(TAG, "prepare failed", e)
            false
        }
        if (!ok) {
            Toast.makeText(this, "Prepare failed", Toast.LENGTH_SHORT).show()
            return false
        }
        return true
    }

    private fun startEventLoop(endpointUrl: String) {
        eventExecutor?.shutdownNow()
        eventExecutor = Executors.newSingleThreadScheduledExecutor()
        eventSequence = 0
        eventExecutor?.scheduleAtFixedRate(
            { sendEvent(endpointUrl, manual = false) },
            3L,
            5L,
            TimeUnit.SECONDS
        )
        eventExecutor?.scheduleAtFixedRate(
            { pollCommandQueue(endpointUrl) },
            2L,
            3L,
            TimeUnit.SECONDS
        )
    }

    private fun sendEventAsync(manual: Boolean) {
        val endpointUrl = binding.urlInput.text?.toString()?.trim().orEmpty()
        if (endpointUrl.isBlank()) return
        (eventExecutor ?: Executors.newSingleThreadScheduledExecutor().also { eventExecutor = it })
            .execute { sendEvent(endpointUrl, manual) }
    }

    private fun sendEvent(endpointUrl: String, manual: Boolean) {
        if (!running && !manual) return
        val seq = ++eventSequence
        val payload = JSONObject().apply {
            put("source", "videomemory-mobile-app")
            put("event_type", if (manual) "mobile_test_event" else "mobile_preview_heartbeat")
            put("deployment_mode", "event")
            put("edge_id", buildEdgeId())
            put("note", if (manual) "Manual test event from phone" else "Phone preview active heartbeat #$seq")
            put("phone_model", "${Build.MANUFACTURER} ${Build.MODEL}")
            put("sequence", seq)
            put("sent_at_ms", System.currentTimeMillis())
        }

        var conn: HttpURLConnection? = null
        try {
            conn = (URL(endpointUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 4000
                readTimeout = 4000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                applyEventAuthHeader(this)
            }
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(payload.toString()) }
            val code = conn.responseCode
            if (code in 200..299) {
                Log.i(TAG, "Event sent seq=$seq code=$code")
                appendEventLog("trigger -> cloud ok (#$seq)")
            } else {
                Log.w(TAG, "Event failed seq=$seq code=$code")
                appendEventLog("trigger -> cloud failed HTTP $code")
                runOnUiThread {
                    Toast.makeText(this, "Event failed: HTTP $code", Toast.LENGTH_SHORT).show()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Event post failed", e)
            appendEventLog("trigger post failed: ${e.message ?: "error"}")
            runOnUiThread {
                Toast.makeText(this, "Event post failed: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        } finally {
            conn?.disconnect()
        }
    }

    private fun pollCommandQueue(triggerEndpointUrl: String) {
        if (!running || appMode != AppMode.EVENT) return
        val pullUrl = deriveEventEndpoint(triggerEndpointUrl, "/api/event/commands/pull")
        val resultUrl = deriveEventEndpoint(triggerEndpointUrl, "/api/event/commands/result")
        var conn: HttpURLConnection? = null
        try {
            val body = JSONObject().apply {
                put("edge_id", buildEdgeId())
                put("max_commands", 2)
                put("client", "videomemory-mobile-app")
            }
            conn = (URL(pullUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 4000
                readTimeout = 4000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                applyEventAuthHeader(this)
            }
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
            val code = conn.responseCode
            if (code == 204) return
            if (code !in 200..299) {
                appendEventLog("poll failed HTTP $code")
                return
            }
            val text = readResponseText(conn)
            val json = JSONObject(text)
            val commands = json.optJSONArray("commands") ?: JSONArray()
            if (commands.length() == 0) return
            appendEventLog("poll -> ${commands.length()} command(s)")
            for (i in 0 until commands.length()) {
                val cmd = commands.optJSONObject(i) ?: continue
                handleQueuedCommand(cmd, resultUrl)
            }
        } catch (e: Exception) {
            appendEventLog("poll error: ${e.message ?: "error"}")
            Log.w(TAG, "pollCommandQueue failed", e)
        } finally {
            conn?.disconnect()
        }
    }

    private fun handleQueuedCommand(cmd: JSONObject, resultUrl: String) {
        val requestId = cmd.optString("request_id", UUID.randomUUID().toString())
        val action = cmd.optString("action", "")
        val args = cmd.optJSONObject("args") ?: JSONObject()
        appendEventLog("cmd <= $action ($requestId)")
        val resultEnvelope = JSONObject().apply {
            put("request_id", requestId)
            put("edge_id", buildEdgeId())
            put("action", action)
        }
        try {
            when (action.lowercase()) {
                "mobile_emit_event", "emit_test_event" -> {
                    sendEventAsync(manual = true)
                    resultEnvelope.put("status", "success")
                    resultEnvelope.put("result", JSONObject().put("message", "manual event emitted"))
                }
                "ping" -> {
                    resultEnvelope.put("status", "success")
                    resultEnvelope.put("result", JSONObject().put("pong", true))
                }
                "list_devices" -> {
                    val devices = edgeDevicesJson()
                    resultEnvelope.put("status", "success")
                    resultEnvelope.put("result", JSONObject().put("devices", devices))
                }
                "list_tasks" -> {
                    val ioIdRaw = args.optString("io_id", "")
                    val ioId = if (ioIdRaw.isBlank()) null else ioIdRaw
                    resultEnvelope.put("status", "success")
                    resultEnvelope.put(
                        "result",
                        JSONObject()
                            .put("tasks", edgeTasksJson(ioId))
                            .put("count", edgeTasksCount(ioId))
                    )
                }
                "get_task" -> {
                    val taskId = args.optString("task_id", "")
                    val taskJson = edgeGetTaskJson(taskId)
                    if (taskJson == null) {
                        resultEnvelope.put("status", "error")
                        resultEnvelope.put("error", "Task not found")
                    } else {
                        resultEnvelope.put("status", "success")
                        resultEnvelope.put("result", JSONObject().put("task", taskJson))
                    }
                }
                "create_task" -> {
                    val ioId = args.optString("io_id", "phone-camera-0").ifBlank { "phone-camera-0" }
                    val desc = args.optString("task_description", "").trim()
                    if (desc.isBlank()) {
                        resultEnvelope.put("status", "error")
                        resultEnvelope.put("error", "task_description is required")
                    } else {
                        val task = edgeCreateTask(ioId, desc)
                        resultEnvelope.put("status", "success")
                        resultEnvelope.put("result", JSONObject().put("task_id", task.taskId).put("task", edgeTaskToJson(task)))
                        sendTaskUpdateEventAsync(task, "Created task from cloud command")
                    }
                }
                "update_task", "edit_task" -> {
                    val taskId = args.optString("task_id", "")
                    val newDesc = args.optString("new_description", args.optString("task_description", "")).trim()
                    val task = edgeUpdateTask(taskId, newDesc)
                    if (task == null) {
                        resultEnvelope.put("status", "error")
                        resultEnvelope.put("error", "Task not found or invalid description")
                    } else {
                        resultEnvelope.put("status", "success")
                        resultEnvelope.put("result", JSONObject().put("task", edgeTaskToJson(task)))
                        sendTaskUpdateEventAsync(task, "Updated task from cloud command")
                    }
                }
                "stop_task" -> {
                    val taskId = args.optString("task_id", "")
                    val task = edgeStopTask(taskId)
                    if (task == null) {
                        resultEnvelope.put("status", "error")
                        resultEnvelope.put("error", "Task not found")
                    } else {
                        resultEnvelope.put("status", "success")
                        resultEnvelope.put("result", JSONObject().put("task", edgeTaskToJson(task)))
                        sendTaskUpdateEventAsync(task, "Stopped task from cloud command")
                    }
                }
                "delete_task" -> {
                    val taskId = args.optString("task_id", "")
                    val deleted = edgeDeleteTask(taskId)
                    if (!deleted) {
                        resultEnvelope.put("status", "error")
                        resultEnvelope.put("error", "Task not found")
                    } else {
                        resultEnvelope.put("status", "success")
                        resultEnvelope.put("result", JSONObject().put("task_id", taskId))
                        appendEventLog("edge task deleted $taskId")
                        renderEdgeState()
                    }
                }
                "show_toast" -> {
                    val msg = args.optString("message", "Cloud command received")
                    runOnUiThread { Toast.makeText(this, msg, Toast.LENGTH_SHORT).show() }
                    resultEnvelope.put("status", "success")
                    resultEnvelope.put("result", JSONObject().put("message", msg))
                }
                else -> {
                    resultEnvelope.put("status", "error")
                    resultEnvelope.put("error", "Unsupported mobile demo action: $action")
                }
            }
        } catch (e: Exception) {
            resultEnvelope.put("status", "error")
            resultEnvelope.put("error", e.message ?: "execution error")
        }
        postCommandResult(resultUrl, resultEnvelope)
    }

    private fun postCommandResult(resultUrl: String, envelope: JSONObject) {
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(resultUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 4000
                readTimeout = 4000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                applyEventAuthHeader(this)
            }
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(envelope.toString()) }
            val code = conn.responseCode
            appendEventLog("result -> cloud ${if (code in 200..299) "ok" else "HTTP $code"}")
        } catch (e: Exception) {
            appendEventLog("result post failed: ${e.message ?: "error"}")
        } finally {
            conn?.disconnect()
        }
    }

    private fun initEdgeServerDemoState() {
        synchronized(edgeStateLock) {
            if (edgeTasks.isNotEmpty()) return
            edgeTasks.add(
                EdgeTask(
                    taskId = "1",
                    ioId = "phone-camera-0",
                    taskDescription = "Watch for motion near the door",
                    status = "active",
                    done = false,
                    notes = mutableListOf("Demo task initialized on device")
                )
            )
            nextEdgeTaskId = 2
        }
    }

    private fun edgeDevicesJson(): JSONArray {
        return JSONArray().put(
            JSONObject()
                .put("io_id", "phone-camera-0")
                .put("name", "${Build.MANUFACTURER} ${Build.MODEL} Camera Preview")
                .put("type", "mobile_preview")
        )
    }

    private fun edgeTasksJson(ioId: String? = null): JSONArray {
        val arr = JSONArray()
        synchronized(edgeStateLock) {
            edgeTasks.filter { ioId == null || it.ioId == ioId }.forEach { arr.put(edgeTaskToJson(it)) }
        }
        return arr
    }

    private fun edgeTasksCount(ioId: String? = null): Int {
        synchronized(edgeStateLock) {
            return edgeTasks.count { ioId == null || it.ioId == ioId }
        }
    }

    private fun edgeGetTaskJson(taskId: String): JSONObject? {
        synchronized(edgeStateLock) {
            return edgeTasks.firstOrNull { it.taskId == taskId }?.let { edgeTaskToJson(it) }
        }
    }

    private fun edgeCreateTask(ioId: String, description: String): EdgeTask {
        val task = synchronized(edgeStateLock) {
            val created = EdgeTask(
                taskId = nextEdgeTaskId.toString(),
                ioId = ioId,
                taskDescription = description,
                status = "active",
                done = false,
                notes = mutableListOf()
            )
            nextEdgeTaskId += 1
            edgeTasks.add(created)
            created
        }
        appendEventLog("edge task created ${task.taskId}")
        renderEdgeState()
        return task
    }

    private fun edgeUpdateTask(taskId: String, newDescription: String): EdgeTask? {
        if (taskId.isBlank() || newDescription.isBlank()) return null
        val task = synchronized(edgeStateLock) {
            edgeTasks.firstOrNull { it.taskId == taskId }?.also {
                it.taskDescription = newDescription
                it.notes.add("Updated from cloud command")
            }
        } ?: return null
        appendEventLog("edge task updated ${task.taskId}")
        renderEdgeState()
        return task
    }

    private fun edgeStopTask(taskId: String): EdgeTask? {
        if (taskId.isBlank()) return null
        val task = synchronized(edgeStateLock) {
            edgeTasks.firstOrNull { it.taskId == taskId }?.also {
                it.done = true
                it.status = "done"
                it.notes.add("Stopped from cloud command")
            }
        } ?: return null
        appendEventLog("edge task stopped ${task.taskId}")
        renderEdgeState()
        return task
    }

    private fun edgeDeleteTask(taskId: String): Boolean {
        if (taskId.isBlank()) return false
        val removed = synchronized(edgeStateLock) { edgeTasks.removeAll { it.taskId == taskId } }
        if (removed) renderEdgeState()
        return removed
    }

    private fun edgeTaskToJson(task: EdgeTask): JSONObject {
        val notes = JSONArray()
        task.notes.takeLast(10).forEach { notes.put(it) }
        return JSONObject()
            .put("task_id", task.taskId)
            .put("io_id", task.ioId)
            .put("task_desc", task.taskDescription)
            .put("status", task.status)
            .put("done", task.done)
            .put("notes", notes)
    }

    private fun renderEdgeState() {
        runOnUiThread {
            if (!::binding.isInitialized) return@runOnUiThread
            val text = synchronized(edgeStateLock) {
                val header = "edge_id: ${buildEdgeId()}\ndevice: phone-camera-0\ntasks: ${edgeTasks.size}"
                val tasksText = if (edgeTasks.isEmpty()) {
                    " - (none)"
                } else {
                    edgeTasks.joinToString("\n") { t ->
                        " - ${t.taskId} [${if (t.done) "done" else t.status}] ${t.taskDescription}"
                    }
                }
                "$header\n$tasksText"
            }
            binding.edgeStateText.text = text
        }
    }

    private fun sendTaskUpdateEventAsync(task: EdgeTask, note: String) {
        val endpointUrl = binding.urlInput.text?.toString()?.trim().orEmpty()
        if (endpointUrl.isBlank() || appMode != AppMode.EVENT) return
        val payload = JSONObject().apply {
            put("source", "videomemory-mobile-app")
            put("event_type", "task_update")
            put("deployment_mode", "event")
            put("edge_id", buildEdgeId())
            put("task_id", task.taskId)
            put("io_id", task.ioId)
            put("task_description", task.taskDescription)
            put("task_status", task.status)
            put("task_done", task.done)
            put("note", note)
            put("sent_at_ms", System.currentTimeMillis())
        }
        (eventExecutor ?: Executors.newSingleThreadScheduledExecutor().also { eventExecutor = it }).execute {
            postEdgeEventPayload(endpointUrl, payload)
        }
    }

    private fun postEdgeEventPayload(endpointUrl: String, payload: JSONObject) {
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(endpointUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 4000
                readTimeout = 4000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                applyEventAuthHeader(this)
            }
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(payload.toString()) }
            val code = conn.responseCode
            appendEventLog("edge task event -> cloud ${if (code in 200..299) "ok" else "HTTP $code"}")
        } catch (e: Exception) {
            appendEventLog("edge task event failed: ${e.message ?: "error"}")
        } finally {
            conn?.disconnect()
        }
    }

    private fun deriveEventEndpoint(triggerUrl: String, path: String): String {
        val idx = triggerUrl.indexOf("/api/event/triggers")
        return if (idx >= 0) {
            triggerUrl.substring(0, idx) + path
        } else {
            triggerUrl.trimEnd('/') + path
        }
    }

    private fun applyEventAuthHeader(conn: HttpURLConnection) {
        val token = binding.tokenInput.text?.toString()?.trim().orEmpty()
        if (token.isNotBlank()) {
            conn.setRequestProperty("Authorization", "Bearer $token")
        }
    }

    private fun readResponseText(conn: HttpURLConnection): String {
        val stream = try {
            conn.inputStream
        } catch (_: Exception) {
            conn.errorStream
        } ?: return ""
        return BufferedReader(InputStreamReader(stream)).use { it.readText() }
    }

    private fun appendEventLog(message: String) {
        val line = "${System.currentTimeMillis() % 100000}: $message"
        synchronized(eventLogLines) {
            eventLogLines.addLast(line)
            while (eventLogLines.size > 8) eventLogLines.removeFirst()
        }
        runOnUiThread {
            if (!::binding.isInitialized) return@runOnUiThread
            val text = synchronized(eventLogLines) { eventLogLines.joinToString("\n") }
            binding.eventLogText.text = text
        }
        Log.i(TAG, message)
    }

    private fun buildEdgeId(): String {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val existing = prefs.getString(KEY_EDGE_ID, null)?.trim()
        if (!existing.isNullOrBlank()) return existing
        val generated = "phone-${Build.MODEL.lowercase().replace(" ", "-")}-${UUID.randomUUID().toString().take(6)}"
        prefs.edit().putString(KEY_EDGE_ID, generated).apply()
        return generated
    }

    private enum class AppMode(val prefValue: String) {
        STREAMING("streaming"),
        EVENT("event"),
    }

    private data class EdgeTask(
        val taskId: String,
        val ioId: String,
        var taskDescription: String,
        var status: String,
        var done: Boolean,
        val notes: MutableList<String>,
    )

    companion object {
        private const val TAG = "VideoMemoryStream"
        private const val PREFS_NAME = "videomemory_stream_prefs"
        private const val KEY_LAST_RTMP_URL = "last_rtmp_url"
        private const val KEY_LAST_EVENT_URL = "last_event_url"
        private const val KEY_APP_MODE = "app_mode"
        private const val KEY_EDGE_ID = "edge_id"
        private const val KEY_EVENT_TOKEN = "event_token"
    }
}
