package com.novelplayer.app.util;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.select.Elements;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import com.novelplayer.app.model.Chapter;
import com.novelplayer.app.model.BookInfo;

public class I275Api {
    private static final String BASE_URL = "https://m.i275.com";
    private static final String USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
    
    private OkHttpClient client;
    private Map<String, List<Chapter>> chapterCache = new HashMap<>();
    private Map<String, Long> cacheTimestamp = new HashMap<>();
    private static final long CACHE_DURATION = 3600000; // 1 hour

    public I275Api() {
        client = new OkHttpClient.Builder()
            .followRedirects(true)
            .build();
    }

    public BookInfo getBookInfo(String bookId) throws IOException {
        String url = BASE_URL + "/book/" + bookId + ".html";
        Request request = new Request.Builder()
            .url(url)
            .addHeader("User-Agent", USER_AGENT)
            .build();
        
        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) throw new IOException("HTTP " + response.code());
            
            String html = response.body().string();
            Document doc = Jsoup.parse(html);
            
            String title = "";
            Element titleTag = doc.selectFirst("title");
            if (titleTag != null) {
                title = titleTag.text();
                title = title.replaceAll("[-_|].*i275.*$", "").trim();
                title = title.replaceAll("[-_|].*听书.*$", "").trim();
            }
            if (title.isEmpty()) title = "书籍 " + bookId;
            
            String cover = "";
            Element img = doc.selectFirst("img[class~=cover|book|img]");
            if (img == null) img = doc.selectFirst("img[src~=cover|book]");
            if (img != null) {
                cover = img.attr("src");
                if (cover.startsWith("//")) cover = "https:" + cover;
            }
            
            return new BookInfo(bookId, title, cover);
        }
    }

    public List<Chapter> getChapterList(String bookId) throws IOException {
        String cacheKey = "i275_" + bookId;
        Long timestamp = cacheTimestamp.get(cacheKey);
        if (timestamp != null && System.currentTimeMillis() - timestamp < CACHE_DURATION) {
            List<Chapter> cached = chapterCache.get(cacheKey);
            if (cached != null) return cached;
        }

        String url = BASE_URL + "/book/" + bookId + ".html";
        Request request = new Request.Builder()
            .url(url)
            .addHeader("User-Agent", USER_AGENT)
            .build();
        
        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) throw new IOException("HTTP " + response.code());
            
            String html = response.body().string();
            Document doc = Jsoup.parse(html);
            
            List<Chapter> chapters = new ArrayList<>();
            Set<String> seen = new LinkedHashSet<>();
            Pattern pattern = Pattern.compile("/play/" + bookId + "/(\\d+)");
            
            Elements links = doc.select("a[href]");
            for (Element link : links) {
                String href = link.attr("href");
                Matcher matcher = pattern.matcher(href);
                if (matcher.find()) {
                    String chapterId = matcher.group(1);
                    String title = link.text().trim();
                    if (!title.isEmpty() && title.length() > 1 && !seen.contains(chapterId)) {
                        seen.add(chapterId);
                        chapters.add(new Chapter(chapterId, title));
                    }
                }
            }
            
            chapterCache.put(cacheKey, chapters);
            cacheTimestamp.put(cacheKey, System.currentTimeMillis());
            return chapters;
        }
    }

    public String getAudioUrl(String bookId, String chapterId) throws IOException {
        String url = BASE_URL + "/play/" + bookId + "/" + chapterId + ".html";
        Request request = new Request.Builder()
            .url(url)
            .addHeader("User-Agent", USER_AGENT)
            .build();
        
        try (Response response = client.newCall(request).execute()) {
            if (!response.isSuccessful()) throw new IOException("HTTP " + response.code());
            
            String html = response.body().string();
            
            // Check if redirected
            if (!response.request().url().toString().contains("/play/")) {
                throw new IOException("无法获取章节页面");
            }
            
            // Extract audio URL using regex
            Pattern pattern = Pattern.compile("url\\s*:\\s*['\"`]([^'\"`\\s]+?)['\"`]");
            Matcher matcher = pattern.matcher(html);
            if (matcher.find()) {
                String audioUrl = matcher.group(1);
                if (audioUrl.startsWith("//")) {
                    audioUrl = "https:" + audioUrl;
                }
                return audioUrl;
            }
            
            throw new IOException("未找到音频地址");
        }
    }

    public void clearCache() {
        chapterCache.clear();
        cacheTimestamp.clear();
    }
}
