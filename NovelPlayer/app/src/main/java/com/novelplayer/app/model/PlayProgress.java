package com.novelplayer.app.model;

import java.io.Serializable;

public class PlayProgress implements Serializable {
    private String bookId;
    private String chapterId;
    private int position;
    private String lastChapter;
    private String updated;

    public PlayProgress() {}

    public String getBookId() { return bookId; }
    public void setBookId(String bookId) { this.bookId = bookId; }
    public String getChapterId() { return chapterId; }
    public void setChapterId(String chapterId) { this.chapterId = chapterId; }
    public int getPosition() { return position; }
    public void setPosition(int position) { this.position = position; }
    public String getLastChapter() { return lastChapter; }
    public void setLastChapter(String lastChapter) { this.lastChapter = lastChapter; }
    public String getUpdated() { return updated; }
    public void setUpdated(String updated) { this.updated = updated; }
}
