import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import { QuickReplyRule, QuickReplyButton } from '../../Service/api/models';

interface ButtonDraft {
  label: string;
  url:   string;
}

interface RuleDraft {
  keyword:    string;
  reply_text: string;
  buttons:    ButtonDraft[];
  is_active:  boolean;
}

@Component({
  standalone: true,
  selector: 'app-quick-reply',
  imports: [CommonModule, FormsModule],
  templateUrl: './quick-reply.component.html',
  styleUrl: './quick-reply.component.scss',
})
export class QuickReplyComponent implements OnInit {
  rules: QuickReplyRule[] = [];
  loading = true;
  errorMsg = '';
  successMsg = '';

  // 新增/編輯表單
  showForm = false;
  editingId: number | null = null;
  draft: RuleDraft = this.emptyDraft();

  saving = false;
  formError = '';

  // 刪除確認
  confirmDeleteId: number | null = null;

  constructor(
    private api: AdminApiService,
    private tokenSvc: AdminTokenService,
    private router: Router,
  ) {}

  ngOnInit() {
    if (!this.tokenSvc.has()) {
      this.router.navigateByUrl('/admin/login');
      return;
    }
    this.load();
  }

  load() {
    this.loading = true;
    this.errorMsg = '';
    this.api.listQuickReplyRules().subscribe({
      next: (items) => {
        this.rules = items;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.errorMsg = '讀取失敗';
      },
    });
  }

  goBack() {
    this.router.navigateByUrl('/admin/turn');
  }

  // ── 表單開關 ───────────────────────────────────────────────

  openCreate() {
    this.editingId = null;
    this.draft = this.emptyDraft();
    this.formError = '';
    this.showForm = true;
  }

  openEdit(rule: QuickReplyRule) {
    this.editingId = rule.id;
    this.draft = {
      keyword:    rule.keyword,
      reply_text: rule.reply_text,
      buttons:    rule.buttons.map(b => ({ label: b.label, url: b.url })),
      is_active:  !!rule.is_active,
    };
    this.formError = '';
    this.showForm = true;
  }

  closeForm() {
    this.showForm = false;
  }

  // ── 按鈕列表操作 ───────────────────────────────────────────

  addButton() {
    if (this.draft.buttons.length >= 13) return;
    this.draft.buttons.push({ label: '', url: '' });
  }

  removeButton(index: number) {
    this.draft.buttons.splice(index, 1);
  }

  // ── 儲存 ───────────────────────────────────────────────────

  save() {
    this.formError = '';
    const keyword = (this.draft.keyword || '').trim();
    const reply_text = (this.draft.reply_text || '').trim();

    if (!keyword) { this.formError = '關鍵字不能為空'; return; }
    if (!reply_text) { this.formError = '回覆文字不能為空'; return; }
    if (this.draft.buttons.length === 0) { this.formError = '至少需要一個按鈕'; return; }

    for (const btn of this.draft.buttons) {
      if (!(btn.label || '').trim()) { this.formError = '按鈕文字不能為空'; return; }
      if (!(btn.url || '').trim()) { this.formError = '按鈕 URL 不能為空'; return; }
    }

    const payload = {
      keyword,
      reply_text,
      buttons: this.draft.buttons.map(b => ({ label: b.label.trim(), url: b.url.trim() })),
      is_active: this.draft.is_active,
    };

    this.saving = true;

    const req$ = this.editingId !== null
      ? this.api.updateQuickReplyRule(this.editingId, payload)
      : this.api.createQuickReplyRule(payload);

    req$.subscribe({
      next: () => {
        this.saving = false;
        this.showForm = false;
        this.flash('儲存成功');
        this.load();
      },
      error: (e) => {
        this.saving = false;
        this.formError = e?.error?.detail ?? '儲存失敗';
      },
    });
  }

  // ── 切換啟用 ───────────────────────────────────────────────

  toggleActive(rule: QuickReplyRule) {
    const newVal = !rule.is_active;
    this.api.updateQuickReplyRule(rule.id, { is_active: newVal }).subscribe({
      next: () => {
        rule.is_active = newVal;
      },
      error: () => {
        this.flash('切換失敗', true);
      },
    });
  }

  // ── 刪除 ───────────────────────────────────────────────────

  askDelete(id: number) {
    this.confirmDeleteId = id;
  }

  cancelDelete() {
    this.confirmDeleteId = null;
  }

  confirmDelete() {
    if (this.confirmDeleteId === null) return;
    const id = this.confirmDeleteId;
    this.confirmDeleteId = null;
    this.api.deleteQuickReplyRule(id).subscribe({
      next: () => {
        this.flash('已刪除');
        this.load();
      },
      error: () => {
        this.flash('刪除失敗', true);
      },
    });
  }

  // ── 工具 ───────────────────────────────────────────────────

  private emptyDraft(): RuleDraft {
    return { keyword: '', reply_text: '', buttons: [{ label: '', url: '' }], is_active: true };
  }

  private flash(msg: string, isErr = false) {
    if (isErr) {
      this.errorMsg = msg;
      setTimeout(() => { this.errorMsg = ''; }, 3000);
    } else {
      this.successMsg = msg;
      setTimeout(() => { this.successMsg = ''; }, 3000);
    }
  }
}
