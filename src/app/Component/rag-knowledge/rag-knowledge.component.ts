import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { AdminApiService } from '../../Service/api/admin-api.service';
import { KnowledgeChunk } from '../../Service/api/models';

type RagCategory = 'faq' | 'course' | 'policy' | 'general';

const CATEGORY_LABEL: Record<RagCategory, string> = {
  faq:     '常見問題',
  course:  '課程資訊',
  policy:  '退費政策',
  general: '一般說明',
};

interface ChunkDraft {
  category: RagCategory;
  title:    string;
  content:  string;
  is_active: number;
}

@Component({
  selector: 'app-rag-knowledge',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './rag-knowledge.component.html',
  styleUrls: ['./rag-knowledge.component.scss'],
})
export class RagKnowledgeComponent implements OnInit {
  chunks: KnowledgeChunk[] = [];
  loading   = false;
  errorMsg  = '';
  successMsg = '';

  filterCategory: RagCategory | '' = '';
  categories: RagCategory[] = ['faq', 'course', 'policy', 'general'];
  categoryLabel = CATEGORY_LABEL;

  // 新增表單
  showAddForm = false;
  draft: ChunkDraft = { category: 'faq', title: '', content: '', is_active: 1 };
  adding = false;
  addError = '';

  // 編輯
  editingId: number | null = null;
  editDraft: ChunkDraft = { category: 'faq', title: '', content: '', is_active: 1 };
  editing = false;
  editError = '';

  // reembed
  reembedding = false;

  constructor(private api: AdminApiService, private cdr: ChangeDetectorRef) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.errorMsg = '';
    const cat = this.filterCategory || undefined;
    this.api.ragList(cat).subscribe({
      next: res => {
        this.chunks = res.items;
        this.loading = false;
        this.cdr.detectChanges();
      },
      error: err => {
        this.errorMsg = err?.error?.detail ?? '載入失敗';
        this.loading = false;
        this.cdr.detectChanges();
      },
    });
  }

  openAdd(): void {
    this.showAddForm = true;
    this.draft = { category: 'faq', title: '', content: '', is_active: 1 };
    this.addError = '';
  }

  cancelAdd(): void {
    this.showAddForm = false;
  }

  submitAdd(): void {
    if (!this.draft.title.trim() || !this.draft.content.trim()) {
      this.addError = '標題與內容為必填';
      return;
    }
    this.adding = true;
    this.addError = '';
    this.api.ragCreate(this.draft).subscribe({
      next: res => {
        this.adding = false;
        this.showAddForm = false;
        this.successMsg = `已新增（id=${res.id}，${res.embedded ? '已建立 embedding' : '⚠️ embedding 未建立'}）`;
        this.load();
        setTimeout(() => { this.successMsg = ''; this.cdr.detectChanges(); }, 4000);
        this.cdr.detectChanges();
      },
      error: err => {
        this.addError = err?.error?.detail ?? '新增失敗';
        this.adding = false;
        this.cdr.detectChanges();
      },
    });
  }

  openEdit(chunk: KnowledgeChunk): void {
    this.editingId = chunk.id;
    this.editDraft = {
      category:  chunk.category,
      title:     chunk.title,
      content:   chunk.content,
      is_active: chunk.is_active,
    };
    this.editError = '';
  }

  cancelEdit(): void {
    this.editingId = null;
  }

  submitEdit(): void {
    if (!this.editDraft.title.trim() || !this.editDraft.content.trim()) {
      this.editError = '標題與內容為必填';
      return;
    }
    this.editing = true;
    this.editError = '';
    this.api.ragUpdate(this.editingId!, this.editDraft).subscribe({
      next: () => {
        this.editing = false;
        this.editingId = null;
        this.successMsg = '已更新';
        this.load();
        setTimeout(() => { this.successMsg = ''; this.cdr.detectChanges(); }, 3000);
        this.cdr.detectChanges();
      },
      error: err => {
        this.editError = err?.error?.detail ?? '更新失敗';
        this.editing = false;
        this.cdr.detectChanges();
      },
    });
  }

  toggleActive(chunk: KnowledgeChunk): void {
    const newVal = chunk.is_active ? 0 : 1;
    this.api.ragUpdate(chunk.id, { is_active: newVal }).subscribe({
      next: () => this.load(),
      error: () => {},
    });
  }

  deleteChunk(chunk: KnowledgeChunk): void {
    if (!confirm(`確定刪除「${chunk.title}」？`)) return;
    this.api.ragDelete(chunk.id).subscribe({
      next: () => {
        this.successMsg = '已刪除';
        this.load();
        setTimeout(() => { this.successMsg = ''; this.cdr.detectChanges(); }, 3000);
        this.cdr.detectChanges();
      },
      error: err => {
        this.errorMsg = err?.error?.detail ?? '刪除失敗';
        this.cdr.detectChanges();
      },
    });
  }

  reembedAll(): void {
    if (!confirm('重新對所有知識片段建立 embedding？這可能需要數分鐘。')) return;
    this.reembedding = true;
    this.api.ragReembedAll().subscribe({
      next: res => {
        this.reembedding = false;
        this.successMsg = `已重新建立 ${res.updated} 個 embedding`;
        this.load();
        setTimeout(() => { this.successMsg = ''; this.cdr.detectChanges(); }, 5000);
        this.cdr.detectChanges();
      },
      error: err => {
        this.reembedding = false;
        this.errorMsg = err?.error?.detail ?? 'reembed 失敗';
        this.cdr.detectChanges();
      },
    });
  }
}
