package com.novelplayer.app.service;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Binder;
import android.os.Build;
import android.os.IBinder;
import android.support.v4.media.MediaMetadataCompat;
import android.support.v4.media.session.MediaSessionCompat;
import android.support.v4.media.session.PlaybackStateCompat;
import androidx.core.app.NotificationCompat;
import com.novelplayer.app.MainActivity;
import com.novelplayer.app.R;
import java.io.IOException;

public class AudioPlayerService extends Service {
    private static final String CHANNEL_ID = "audio_playback";
    private static final int NOTIFICATION_ID = 1;
    
    private MediaPlayer mediaPlayer;
    private MediaSessionCompat mediaSession;
    private final IBinder binder = new AudioBinder();
    private String currentUrl = "";
    private String bookTitle = "";
    private String chapterTitle = "";
    private boolean isPrepared = false;
    private OnPlaybackStateChangedListener listener;

    public interface OnPlaybackStateChangedListener {
        void onPlaybackStateChanged(boolean isPlaying, int position, int duration);
        void onCompletion();
        void onError(String error);
    }

    public class AudioBinder extends Binder {
        public AudioPlayerService getService() {
            return AudioPlayerService.this;
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        mediaPlayer = new MediaPlayer();
        mediaPlayer.setAudioAttributes(
            new AudioAttributes.Builder()
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .build()
        );
        mediaPlayer.setOnPreparedListener(mp -> {
            isPrepared = true;
            mp.start();
            updateNotification();
            if (listener != null) {
                listener.onPlaybackStateChanged(true, 0, mp.getDuration());
            }
        });
        mediaPlayer.setOnCompletionListener(mp -> {
            isPrepared = false;
            if (listener != null) {
                listener.onCompletion();
            }
        });
        mediaPlayer.setOnErrorListener((mp, what, extra) -> {
            isPrepared = false;
            if (listener != null) {
                listener.onError("播放错误: " + what + "," + extra);
            }
            return true;
        });

        setupMediaSession();
    }

    private void setupMediaSession() {
        mediaSession = new MediaSessionCompat(this, "AudioPlayerService");
        mediaSession.setFlags(MediaSessionCompat.FLAG_HANDLES_MEDIA_BUTTONS | MediaSessionCompat.FLAG_HANDLES_TRANSPORT_CONTROLS);
        
        mediaSession.setCallback(new MediaSessionCompat.Callback() {
            @Override
            public void onPlay() {
                resume();
            }

            @Override
            public void onPause() {
                pause();
            }

            @Override
            public void onSkipToNext() {
                if (listener != null) {
                    // Trigger next chapter from MainActivity
                }
            }

            @Override
            public void onSkipToPrevious() {
                if (listener != null) {
                    // Trigger previous chapter from MainActivity
                }
            }
        });

        mediaSession.setActive(true);
    }

    @Override
    public IBinder onBind(Intent intent) {
        return binder;
    }

    public void setListener(OnPlaybackStateChangedListener listener) {
        this.listener = listener;
    }

    public void play(String url, String bookTitle, String chapterTitle) {
        try {
            this.currentUrl = url;
            this.bookTitle = bookTitle;
            this.chapterTitle = chapterTitle;
            isPrepared = false;
            mediaPlayer.reset();
            mediaPlayer.setDataSource(url);
            mediaPlayer.prepareAsync();
            startForeground(NOTIFICATION_ID, createNotification());
        } catch (IOException e) {
            e.printStackTrace();
            if (listener != null) {
                listener.onError("加载音频失败: " + e.getMessage());
            }
        }
    }

    public void pause() {
        if (mediaPlayer != null && mediaPlayer.isPlaying()) {
            mediaPlayer.pause();
            updateNotification();
            if (listener != null) {
                listener.onPlaybackStateChanged(false, mediaPlayer.getCurrentPosition(), mediaPlayer.getDuration());
            }
        }
    }

    public void resume() {
        if (mediaPlayer != null && isPrepared && !mediaPlayer.isPlaying()) {
            mediaPlayer.start();
            updateNotification();
            if (listener != null) {
                listener.onPlaybackStateChanged(true, mediaPlayer.getCurrentPosition(), mediaPlayer.getDuration());
            }
        }
    }

    public void seekTo(int position) {
        if (mediaPlayer != null && isPrepared) {
            mediaPlayer.seekTo(position);
            if (listener != null) {
                listener.onPlaybackStateChanged(mediaPlayer.isPlaying(), position, mediaPlayer.getDuration());
            }
        }
    }

    public void setPlaybackSpeed(float speed) {
        if (mediaPlayer != null && isPrepared && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            mediaPlayer.setPlaybackParams(mediaPlayer.getPlaybackParams().setSpeed(speed));
        }
    }

    public boolean isPlaying() {
        return mediaPlayer != null && mediaPlayer.isPlaying();
    }

    public int getCurrentPosition() {
        return mediaPlayer != null ? mediaPlayer.getCurrentPosition() : 0;
    }

    public int getDuration() {
        return mediaPlayer != null ? mediaPlayer.getDuration() : 0;
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "音频播放",
                NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("小说播放器后台播放通知");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    private Notification createNotification() {
        Intent intent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(bookTitle)
            .setContentText(chapterTitle)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setShowWhen(false)
            .setStyle(new androidx.media.app.NotificationCompat.MediaStyle()
                .setMediaSession(mediaSession.getSessionToken())
                .setShowActionsInCompactView(0, 1, 2))
            .addAction(new NotificationCompat.Action.Builder(
                R.drawable.ic_prev,
                "上一章",
                createPendingIntent("PREV"))
                .build())
            .addAction(new NotificationCompat.Action.Builder(
                mediaPlayer.isPlaying() ? R.drawable.ic_pause : R.drawable.ic_play,
                mediaPlayer.isPlaying() ? "暂停" : "播放",
                createPendingIntent("PLAY_PAUSE"))
                .build())
            .addAction(new NotificationCompat.Action.Builder(
                R.drawable.ic_next,
                "下一章",
                createPendingIntent("NEXT"))
                .build());

        return builder.build();
    }

    private void updateNotification() {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify(NOTIFICATION_ID, createNotification());
        }
    }

    private PendingIntent createPendingIntent(String action) {
        Intent intent = new Intent(this, AudioPlayerService.class);
        intent.setAction(action);
        return PendingIntent.getService(this, action.hashCode(), intent, PendingIntent.FLAG_IMMUTABLE);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            String action = intent.getAction();
            if (action != null) {
                switch (action) {
                    case "PLAY_PAUSE":
                        if (isPlaying()) pause();
                        else resume();
                        break;
                    case "PREV":
                        // Handle previous
                        break;
                    case "NEXT":
                        // Handle next
                        break;
                }
            }
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        if (mediaPlayer != null) {
            mediaPlayer.release();
            mediaPlayer = null;
        }
        if (mediaSession != null) {
            mediaSession.release();
        }
    }
}
