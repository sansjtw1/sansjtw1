package com.novelplayer.app.adapter;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;
import com.novelplayer.app.R;
import com.novelplayer.app.model.Chapter;
import java.util.ArrayList;
import java.util.List;

public class ChapterAdapter extends RecyclerView.Adapter<ChapterAdapter.ViewHolder> {
    private List<Chapter> chapters = new ArrayList<>();
    private List<Chapter> filteredChapters = new ArrayList<>();
    private int currentIndex = -1;
    private OnChapterClickListener clickListener;
    private String filterKeyword = "";

    public interface OnChapterClickListener {
        void onChapterClick(int position);
    }

    public void setOnChapterClickListener(OnChapterClickListener listener) {
        this.clickListener = listener;
    }

    public void setChapters(List<Chapter> chapters) {
        this.chapters = chapters;
        applyFilter();
    }

    public void setCurrentIndex(int index) {
        int oldIndex = currentIndex;
        currentIndex = index;
        if (oldIndex >= 0) notifyItemChanged(oldIndex);
        if (index >= 0) notifyItemChanged(index);
    }

    public void filter(String keyword) {
        this.filterKeyword = keyword;
        applyFilter();
    }

    private void applyFilter() {
        filteredChapters.clear();
        if (filterKeyword.isEmpty()) {
            filteredChapters.addAll(chapters);
        } else {
            String lower = filterKeyword.toLowerCase();
            for (int i = 0; i < chapters.size(); i++) {
                Chapter ch = chapters.get(i);
                if (ch.getTitle().toLowerCase().contains(lower) || String.valueOf(i + 1).contains(filterKeyword)) {
                    filteredChapters.add(ch);
                }
            }
        }
        notifyDataSetChanged();
    }

    public int getOriginalPosition(int filteredPosition) {
        Chapter ch = filteredChapters.get(filteredPosition);
        return chapters.indexOf(ch);
    }

    @NonNull
    @Override
    public ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View view = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_chapter, parent, false);
        return new ViewHolder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull ViewHolder holder, int position) {
        Chapter chapter = filteredChapters.get(position);
        int originalPos = chapters.indexOf(chapter);
        holder.numText.setText(String.valueOf(originalPos + 1));
        holder.titleText.setText(chapter.getTitle());
        holder.playingIndicator.setVisibility(originalPos == currentIndex ? View.VISIBLE : View.GONE);
        holder.itemView.setBackgroundResource(
            originalPos == currentIndex ? R.drawable.bg_chapter_active : R.drawable.bg_chapter_normal
        );
        holder.itemView.setOnClickListener(v -> {
            if (clickListener != null) {
                clickListener.onChapterClick(originalPos);
            }
        });
    }

    @Override
    public int getItemCount() {
        return filteredChapters.size();
    }

    static class ViewHolder extends RecyclerView.ViewHolder {
        TextView numText, titleText, playingIndicator;

        ViewHolder(@NonNull View itemView) {
            super(itemView);
            numText = itemView.findViewById(R.id.ch_num);
            titleText = itemView.findViewById(R.id.ch_title);
            playingIndicator = itemView.findViewById(R.id.ch_playing);
        }
    }
}
