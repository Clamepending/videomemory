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
import com.pedro.common.ConnectChecker
import com.pedro.library.rtmp.RtmpStream
import com.videomemory.stream.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity(), ConnectChecker {

    private lateinit var binding: ActivityMainBinding
    private var rtmpStream: RtmpStream? = null
    private var streaming = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        requestPermissions()
        binding.preview.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(h: SurfaceHolder) {}
            override fun surfaceChanged(h: SurfaceHolder, format: Int, width: Int, height: Int) {}
            override fun surfaceDestroyed(h: SurfaceHolder) {}
        })
        binding.btnStart.setOnClickListener { startStream() }
        binding.btnStop.setOnClickListener { stopStream() }
    }

    private fun requestPermissions() {
        val perms = arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (perms.any { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }) {
            ActivityCompat.requestPermissions(this, perms, 0)
        }
    }

    private fun startStream() {
        val url = binding.urlInput.text.toString().trim()
        if (url.isBlank()) {
            Toast.makeText(this, "Enter RTMP URL", Toast.LENGTH_SHORT).show()
            return
        }
        if (!url.startsWith("rtmp://", ignoreCase = true)) {
            Toast.makeText(this, "URL must start with rtmp://", Toast.LENGTH_SHORT).show()
            return
        }
        if (rtmpStream == null) {
            rtmpStream = RtmpStream(this, this)
            val ok = rtmpStream!!.prepareVideo(1280, 720, 1_200_000) &&
                rtmpStream!!.prepareAudio(48000, true, 128 * 1024)
            if (!ok) {
                Toast.makeText(this, "Prepare failed", Toast.LENGTH_SHORT).show()
                rtmpStream = null
                return
            }
        }
        rtmpStream!!.startPreview(binding.preview)
        rtmpStream!!.startStream(url)
        streaming = true
        binding.btnStart.isEnabled = false
        binding.btnStop.isEnabled = true
        binding.urlInput.isEnabled = false
    }

    private fun stopStream() {
        rtmpStream?.stopStream()
        rtmpStream?.stopPreview()
        streaming = false
        binding.btnStart.isEnabled = true
        binding.btnStop.isEnabled = false
        binding.urlInput.isEnabled = true
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
        rtmpStream?.release()
        rtmpStream = null
        super.onDestroy()
    }

    companion object {
        private const val TAG = "VideoMemoryStream"
    }
}
