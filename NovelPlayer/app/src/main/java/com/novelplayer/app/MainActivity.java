package com.novelplayer.app;

import android.Manifest;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.ProgressBar;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;
import com.bumptech.glide.Glide;
import com.google.android.material.button.MaterialButton;
import com.google.android.material.tabs.TabLayout;
import com.novelplayer.app.adapter.ChapterAdapter;
import com.novelplayer.app.model.BookInfo;
import com.novelplayer.app.model.Chapter;
import com.novelplayer.app.service.AudioPlayerService;
import com.novelplayer.app.util.I275Api;
import com.novelplayer.app.util.MediaDetector;
import com.novelplayer.app.util.ProgressManager;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

public class MainActivity extends AppCompatActivity implements AudioPlayerService.OnPlaybackStateChangedListener {
    
    // Views
    private TabLayout tabLayout;
    private View novelPage, detectPage;
    private View novelHome, novelPlayer;
    private EditText novelUrlInput;
    private MaterialButton startPlayBtn;
    private TextView bookTitleText, chapterTitleText, bookMetaText;
    private ImageView bookCoverImage;
    private SeekBar progressSeek;
    private TextView currentTimeText, totalTimeText;
    private MaterialButton prevChapterBtn, playPauseBtn, nextChapterBtn;
    private MaterialButton speed075Btn, speed1Btn, speed125Btn, speed15Btn, speed2Btn;
    private RecyclerView chapterList;
    private EditText chapterSearch;
    private TextView chapterCountText;
    private View loadingOverlay;
    private TextView loadingText;
    
    // Detect page views
    private EditText detectUrlInput;
    private EditText detectSourceInput;
    private RecyclerView detectResultsList;
    private TextView detectCountText;
    
    // Service
    private AudioPlayerService playerService;
    private boolean serviceBound = false;
    
    // Data
    private I275Api api;
    private ProgressManager progressManager;
    private ChapterAdapter chapterAdapter;
    private List<Chapter> chapters = new ArrayList<>();
    private String currentBookId = "";
    private String currentBookTitle = "";
    private int currentChapterIndex = -1;
    private float currentSpeed = 1.0f;
    private Handler handler = new Handler(Looper.getMainLooper());
    private ExecutorService executor = Executors.newCachedThreadPool();
    
    // Permission
    private static final int PERMISSION_REQUEST_CODE = 100;
    
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        
        api = new I275Api();
        progressManager = new ProgressManager(this);
        
        initViews();
        setupListeners();
        checkPermissions();
    }
    
    private void initViews() {
        tabLayout = findViewById(R.id.tab_layout);
        novelPage = findViewById(R.id.novel_page);
        detectPage = findViewById(R.id.detect_page);
        novelHome = findViewById(R.id.novel_home);
        novelPlayer = findViewById(R.id.novel_player);
        novelUrlInput = findViewById(R.id.novel_url_input);
        startPlayBtn = findViewById(R.id.start_play_btn);
        bookTitleText = findViewById(R.id.book_title);
        chapterTitleText = findViewById(R.id.chapter_title);
        bookMetaText = findViewById(R.id.book_meta);
        bookCoverImage = findViewById(R.id.book_cover);
        progressSeek = findViewById(R.id.progress_seek);
        currentTimeText = findViewById(R.id.current_time);
        totalTimeText = findViewById(R.id.total_time);
        prevChapterBtn = findViewById(R.id.prev_chapter_btn);
        playPauseBtn = findViewById(R.id.play_pause_btn);
        nextChapterBtn = findViewById(R.id.next_chapter_btn);
        speed075Btn = findViewById(R.id.speed_075_btn);
        speed1Btn = findViewById(R.id.speed_1_btn);
        speed125Btn = findViewById(R.id.speed_125_btn);
        speed15Btn = findViewById(R.id.speed_15_btn);
        speed2Btn = findViewById(R.id.speed_2_btn);
        chapterList = findViewById(R.id.chapter_list);
        chapterSearch = findViewById(R.id.chapter_search);
        chapterCountText = findViewById(R.id.chapter_count);
        loadingOverlay = findViewById(R.id.loading_overlay);
        loadingText = findViewById(R.id.loading_text);
        
        detectUrlInput = findViewById(R.id.detect_url_input);
        detectSourceInput = findViewById(R.id.detect_source_input);
        detectResultsList = findViewById(R.id.detect_results_list);
        detectCountText = findViewById(R.id.detect_count);
        
        chapterAdapter = new ChapterAdapter();
        chapterList.setLayoutManager(new LinearLayoutManager(this));
        chapterList.setAdapter(chapterAdapter);
        
        detectResultsList.setLayoutManager(new LinearLayoutManager(this));
    }
    
    private void setupListeners() {
        tabLayout.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override
            public void onTabSelected(TabLayout.Tab tab) {
                if (tab.getPosition() == 0) {
                    novelPage.setVisibility(View.VISIBLE);
                    detectPage.setVisibility(View.GONE);
                } else {
                    novelPage.setVisibility(View.GONE);
                    detectPage.setVisibility(View.VISIBLE);
                }
            }
            
            @Override
            public void onTabUnselected(TabLayout.Tab tab) {}
            
            @Override
            public void onTabReselected(TabLayout.Tab tab) {}
        });
        
        startPlayBtn.setOnClickListener(v -> startNovel());
        
        prevChapterBtn.setOnClickListener(v -> prevChapter());
        playPauseBtn.setOnClickListener(v -> togglePlayPause());
        nextChapterBtn.setOnClickListener(v -> nextChapter());
        
        speed075Btn.setOnClickListener(v -> setSpeed(0.75f));
        speed1Btn.setOnClickListener(v -> setSpeed(1.0f));
        speed125Btn.setOnClickListener(v -> setSpeed(1.25f));
        speed15Btn.setOnClickListener(v -> setSpeed(1.5f));
        speed2Btn.setOnClickListener(v -> setSpeed(2.0f));
        
        progressSeek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                if (fromUser && serviceBound) {
                    playerService.seekTo(progress);
                }
            }
            
            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {}
            
            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {}
        });
        
        chapterSearch.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            
            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                chapterAdapter.filter(s.toString());
            }
            
            @Override
            public void afterTextChanged(Editable s) {}
        });
        
        chapterAdapter.setOnChapterClickListener(position -> {
            playChapter(position);
        });
        
        findViewById(R.id.detect_url_btn).setOnClickListener(v -> detectFromUrl());
        findViewById(R.id.detect_source_btn).setOnClickListener(v -> detectFromSource());
    }
    
    private void checkPermissions() {
        List<String> permissions = new ArrayList<>();
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                permissions.add(Manifest.permission.POST_NOTIFICATIONS);
            }
        }
        
        if (!permissions.isEmpty()) {
            ActivityCompat.requestPermissions(this, permissions.toArray(new String[0]), PERMISSION_REQUEST_CODE);
        }
    }
    
    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == PERMISSION_REQUEST_CODE) {
            for (int result : grantResults) {
                if (result != PackageManager.PERMISSION_GRANTED) {
                    Toast.makeText(this, "需要权限才能正常使用后台播放功能", Toast.LENGTH_LONG).show();
                    break;
                }
            }
        }
    }
    
    private void startNovel() {
        String url = novelUrlInput.getText().toString().trim();
        if (url.isEmpty()) {
            Toast.makeText(this, "请输入播放地址", Toast.LENGTH_SHORT).show();
            return;
        }
        
        Pattern pattern = Pattern.compile("i275\\.com/play/(\\d+)/(\\d+)");
        Matcher matcher = pattern.matcher(url);
        if (!matcher.find()) {
            Toast.makeText(this, "请输入有效的 i275.com 播放地址", Toast.LENGTH_SHORT).show();
            return;
        }
        
        String bookId = matcher.group(1);
        String chapterId = matcher.group(2);
        
        showLoading("正在加载书籍信息...");
        
        executor.execute(() -> {
            try {
                BookInfo bookInfo = api.getBookInfo(bookId);
                List<Chapter> chapterList = api.getChapterList(bookId);
                
                runOnUiThread(() -> {
                    currentBookId = bookId;
                    currentBookTitle = bookInfo.getTitle();
                    chapters.clear();
                    chapters.addAll(chapterList);
                    
                    bookTitleText.setText(bookInfo.getTitle());
                    bookMetaText.setText("共 " + chapters.size() + " 章");
                    chapterCountText.setText(String.valueOf(chapters.size()));
                    
                    if (!bookInfo.getCover().isEmpty()) {
                        Glide.with(this).load(bookInfo.getCover()).into(bookCoverImage);
                    }
                    
                    chapterAdapter.setChapters(chapters);
                    
                    int chapterIndex = -1;
                    for (int i = 0; i < chapters.size(); i++) {
                        if (chapters.get(i).getId().equals(chapterId)) {
                            chapterIndex = i;
                            break;
                        }
                    }
                    if (chapterIndex == -1) chapterIndex = 0;
                    
                    novelHome.setVisibility(View.GONE);
                    novelPlayer.setVisibility(View.VISIBLE);
                    
                    hideLoading();
                    playChapter(chapterIndex);
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    hideLoading();
                    Toast.makeText(this, "加载失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        });
    }
    
    private void playChapter(int index) {
        if (index < 0 || index >= chapters.size()) return;
        
        currentChapterIndex = index;
        Chapter chapter = chapters.get(index);
        
        chapterTitleText.setText("第 " + (index + 1) + " 章：" + chapter.getTitle());
        chapterAdapter.setCurrentIndex(index);
        progressSeek.setProgress(0);
        currentTimeText.setText("00:00");
        totalTimeText.setText("加载中...");
        
        showLoading("正在加载音频...");
        
        executor.execute(() -> {
            try {
                String audioUrl = api.getAudioUrl(currentBookId, chapter.getId());
                
                runOnUiThread(() -> {
                    hideLoading();
                    
                    if (!serviceBound) {
                        Intent intent = new Intent(this, AudioPlayerService.class);
                        bindService(intent, serviceConnection, Context.BIND_AUTO_CREATE);
                        startForegroundService(intent);
                    } else {
                        playerService.play(audioUrl, currentBookTitle, chapter.getTitle());
                        playerService.setPlaybackSpeed(currentSpeed);
                    }
                    
                    progressManager.saveProgress(currentBookId, chapter.getId(), 0);
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    hideLoading();
                    Toast.makeText(this, "加载音频失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        });
    }
    
    private void togglePlayPause() {
        if (!serviceBound) return;
        
        if (playerService.isPlaying()) {
            playerService.pause();
            playPauseBtn.setText("▶");
        } else {
            playerService.resume();
            playPauseBtn.setText("⏸");
        }
    }
    
    private void prevChapter() {
        if (currentChapterIndex > 0) {
            playChapter(currentChapterIndex - 1);
        } else {
            Toast.makeText(this, "已经是第一章了", Toast.LENGTH_SHORT).show();
        }
    }
    
    private void nextChapter() {
        if (currentChapterIndex < chapters.size() - 1) {
            playChapter(currentChapterIndex + 1);
        } else {
            Toast.makeText(this, "已经是最后一章了", Toast.LENGTH_SHORT).show();
        }
    }
    
    private void setSpeed(float speed) {
        currentSpeed = speed;
        if (serviceBound) {
            playerService.setPlaybackSpeed(speed);
        }
        
        speed075Btn.setAlpha(speed == 0.75f ? 1.0f : 0.5f);
        speed1Btn.setAlpha(speed == 1.0f ? 1.0f : 0.5f);
        speed125Btn.setAlpha(speed == 1.25f ? 1.0f : 0.5f);
        speed15Btn.setAlpha(speed == 1.5f ? 1.0f : 0.5f);
        speed2Btn.setAlpha(speed == 2.0f ? 1.0f : 0.5f);
    }
    
    private void detectFromUrl() {
        String url = detectUrlInput.getText().toString().trim();
        if (url.isEmpty()) {
            Toast.makeText(this, "请输入网页地址", Toast.LENGTH_SHORT).show();
            return;
        }
        
        showLoading("正在检测音频...");
        
        executor.execute(() -> {
            try {
                List<MediaDetector.MediaResult> results = MediaDetector.detectFromUrl(url, true);
                runOnUiThread(() -> {
                    hideLoading();
                    showDetectResults(results);
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    hideLoading();
                    Toast.makeText(this, "检测失败: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        });
    }
    
    private void detectFromSource() {
        String source = detectSourceInput.getText().toString().trim();
        if (source.isEmpty()) {
            Toast.makeText(this, "请粘贴网页源码", Toast.LENGTH_SHORT).show();
            return;
        }
        
        showLoading("正在分析源码...");
        
        executor.execute(() -> {
            List<MediaDetector.MediaResult> results = MediaDetector.detectFromHtml(source);
            runOnUiThread(() -> {
                hideLoading();
                showDetectResults(results);
            });
        });
    }
    
    private void showDetectResults(List<MediaDetector.MediaResult> results) {
        detectCountText.setText("检测到 " + results.size() + " 个媒体");
        // TODO: Implement MediaResultAdapter
        Toast.makeText(this, "检测到 " + results.size() + " 个媒体资源", Toast.LENGTH_SHORT).show();
    }
    
    private void showLoading(String text) {
        loadingText.setText(text);
        loadingOverlay.setVisibility(View.VISIBLE);
    }
    
    private void hideLoading() {
        loadingOverlay.setVisibility(View.GONE);
    }
    
    @Override
    public void onPlaybackStateChanged(boolean isPlaying, int position, int duration) {
        runOnUiThread(() -> {
            playPauseBtn.setText(isPlaying ? "⏸" : "▶");
            progressSeek.setMax(duration);
            progressSeek.setProgress(position);
            currentTimeText.setText(formatTime(position));
            totalTimeText.setText(formatTime(duration));
        });
    }
    
    @Override
    public void onCompletion() {
        runOnUiThread(() -> {
            nextChapter();
        });
    }
    
    @Override
    public void onError(String error) {
        runOnUiThread(() -> {
            Toast.makeText(this, error, Toast.LENGTH_LONG).show();
        });
    }
    
    private ServiceConnection serviceConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder service) {
            AudioPlayerService.AudioBinder binder = (AudioPlayerService.AudioBinder) service;
            playerService = binder.getService();
            serviceBound = true;
            playerService.setListener(MainActivity.this);
        }
        
        @Override
        public void onServiceDisconnected(ComponentName name) {
            serviceBound = false;
        }
    };
    
    private String formatTime(int millis) {
        int seconds = millis / 1000;
        int minutes = seconds / 60;
        seconds = seconds % 60;
        return String.format("%02d:%02d", minutes, seconds);
    }
    
    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (serviceBound) {
            unbindService(serviceConnection);
        }
        executor.shutdown();
    }
}
