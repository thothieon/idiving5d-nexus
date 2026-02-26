// ticket-detail.component.ts
import {
  Component, OnInit, OnDestroy, AfterViewChecked,
  ElementRef, ViewChild, inject, DestroyRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { interval, Subscription } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { AdminApiService }   from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import {
  TicketMessage, SessionHistory, AllowedNext,
  CustomerNote,
  SessionStatus, SESSION_STATUS_LABEL, SESSION_STATUS_COLOR,
} from '../../Service/api/models';

@Component({
  standalone: true,
  selector:   'app-ticket-detail',
  imports:    [CommonModule, FormsModule, RouterLink],
  templateUrl: './ticket-detail.component.html',
  styleUrl:    './ticket-detail.component.scss',
})
export class TicketDetailComponent implements OnInit, OnDestroy, AfterViewChecked {
  private destroyRef = inject(DestroyRef);
  @ViewChild('chatBottom') private chatBottom!: ElementRef;

  // ── 基本 ────────────────────────────────────────────────
  ticketId     = 0;
  loading      = false;
  sending      = false;
  errorMsg     = '';
  draft        = '';
  customerName = '';
  customerId: number | null = null;

  // ── 訊息 ────────────────────────────────────────────────
  items: TicketMessage[] = [];
  private shouldScrollBottom = false;

  // ── 狀態機 ──────────────────────────────────────────────
  currentStatus: SessionStatus = 'new';
  currentStatusLabel = '';
  allowedNext: AllowedNext[]   = [];
  sessionHistory: SessionHistory[] = [];
  transitioning = false;

  // ── 右側抽屜 ────────────────────────────────────────────
  showPanel = false;
  rightTab: 'status' | 'notes' | 'history' = 'status';

  // ── 筆記 ────────────────────────────────────────────────
  notes: CustomerNote[]  = [];
  noteDraft              = '';
  noteSubmitting         = false;
  editingNoteId: number | null = null;
  editingNoteDraft       = '';

  // ── Viewer ──────────────────────────────────────────────
  viewerOpen = false;
  viewerSrc  = '';
  viewerName = '';

  // ── 媒體快取 ─────────────────────────────────────────────
  private mediaCache   = new Map<string, string>();
  private mediaLoading = new Set<string>();

  // ── Polling ──────────────────────────────────────────────
  private pollSub?: Subscription;

  constructor(
    private route:    ActivatedRoute,
    private router:   Router,
    private api:      AdminApiService,
    private tokenSvc: AdminTokenService,
  ) {
    this.destroyRef.onDestroy(() => {
      for (const u of this.mediaCache.values()) URL.revokeObjectURL(u);
      this.mediaCache.clear();
    });
  }

  // ── 生命週期 ─────────────────────────────────────────────

  ngOnInit() {
    if (!this.tokenSvc.has()) {
      this.router.navigateByUrl('/admin/login');
      return;
    }
    this.ticketId = Number(this.route.snapshot.paramMap.get('id') || '0');
    if (!this.ticketId) {
      this.router.navigateByUrl('/admin/turn');
      return;
    }
    this.loadAll();
    this.startPolling();
  }

  ngOnDestroy() {
    this.pollSub?.unsubscribe();
  }

  ngAfterViewChecked() {
    if (this.shouldScrollBottom) {
      this.scrollToBottom();
      this.shouldScrollBottom = false;
    }
  }

  private scrollToBottom() {
    try { this.chatBottom?.nativeElement?.scrollIntoView({ behavior: 'smooth' }); } catch {}
  }

  // ── 載入 ─────────────────────────────────────────────────

  loadAll() {
    this.refresh();
    this.loadStatus();
    this.loadNotes();
    this.loadHistory();
  }

  refresh() {
    this.loading  = true;
    this.errorMsg = '';
    this.api.getMessages(this.ticketId, 200).subscribe({
      next: rows => {
        this.items   = rows || [];
        this.loading = false;
        this.shouldScrollBottom = true;
        const lastIn = [...this.items].reverse().find(m => m.direction === 'in');
        if (lastIn?.sender_name) this.customerName = lastIn.sender_name;
      },
      error: () => {
        this.loading  = false;
        this.errorMsg = '讀取訊息失敗（可能 token 失效或 API 無法連線）';
        this.router.navigateByUrl('/admin/login');
      },
    });
  }

  loadStatus() {
    this.api.getTicketStatus(this.ticketId).subscribe({
      next: res => {
        this.currentStatus      = res.current;
        this.currentStatusLabel = res.current_label;
        this.allowedNext        = res.allowed_next;
      },
    });
  }

  loadNotes() {
    this.api.getNotes(this.ticketId).subscribe({
      next: res => {
        this.customerId = res.customer_id;
        this.notes      = res.items ?? [];
      },
    });
  }

  loadHistory() {
    this.api.getSessionHistory(this.ticketId).subscribe({
      next: rows => this.sessionHistory = rows,
    });
  }

  // ── Polling ──────────────────────────────────────────────

  private startPolling() {
    this.pollSub = interval(5000)
      .pipe(switchMap(() => this.api.getMessages(this.ticketId)))
      .subscribe({
        next: msgs => {
          if (msgs.length !== this.items.length) {
            this.items = msgs;
            this.shouldScrollBottom = true;
            this.loadStatus();
          }
        },
      });
  }

  // ── 回覆 ─────────────────────────────────────────────────

  send() {
    const text = (this.draft || '').trim();
    if (!text || this.sending) return;

    const backup  = text;
    this.draft    = '';
    this.sending  = true;
    this.errorMsg = '';

    this.api.reply(this.ticketId, text).subscribe({
      next: () => {
        this.sending = false;
        this.refresh();
        this.loadStatus();
      },
      error: err => {
        this.sending = false;
        this.draft   = backup;
        const backend = err?.error?.error || err?.error?.message || err?.error?.detail;
        this.errorMsg = backend || `送出失敗（HTTP ${err?.status || '??'}）`;
      },
    });
  }

  onEnter(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  // ── 結案 ─────────────────────────────────────────────────

  close() {
    if (!confirm('確定要結案？')) return;
    this.api.close(this.ticketId).subscribe({
      next:  () => this.router.navigateByUrl('/admin/turn'),
      error: () => this.errorMsg = '結案失敗',
    });
  }

  // ── 狀態轉移 ─────────────────────────────────────────────

  doTransition(status: SessionStatus) {
    if (this.transitioning) return;
    this.transitioning = true;
    this.api.transition(this.ticketId, status).subscribe({
      next: () => {
        this.transitioning = false;
        this.loadStatus();
        this.loadHistory();
      },
      error: err => {
        this.transitioning = false;
        this.errorMsg = err?.error?.detail || '狀態切換失敗';
      },
    });
  }

  // ── 筆記 ─────────────────────────────────────────────────

  submitNote() {
    const text = (this.noteDraft || '').trim();
    if (!text || this.noteSubmitting) return;
    this.noteSubmitting = true;
    this.api.createNote(this.ticketId, text).subscribe({
      next: () => {
        this.noteDraft      = '';
        this.noteSubmitting = false;
        this.loadNotes();
      },
      error: () => {
        this.noteSubmitting = false;
        this.errorMsg = '新增筆記失敗';
      },
    });
  }

  startEdit(n: CustomerNote) {
    this.editingNoteId    = n.id;
    this.editingNoteDraft = n.note;
  }

  cancelEdit() {
    this.editingNoteId    = null;
    this.editingNoteDraft = '';
  }

  saveEdit(n: CustomerNote) {
    const text = (this.editingNoteDraft || '').trim();
    if (!text) return;
    this.api.updateNote(this.ticketId, n.id, text).subscribe({
      next: () => {
        this.cancelEdit();
        this.loadNotes();
      },
      error: () => this.errorMsg = '更新筆記失敗',
    });
  }

  deleteNote(n: CustomerNote) {
    if (!confirm('確定刪除這則筆記？')) return;
    this.api.deleteNote(this.ticketId, n.id).subscribe({
      next:  () => this.loadNotes(),
      error: () => this.errorMsg = '刪除筆記失敗',
    });
  }

  onNoteEnter(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submitNote();
    }
  }

  // ── 訊息類型 ─────────────────────────────────────────────

  bodyType(m: any): 'image' | 'video' | 'audio' | 'file' | 'sticker' | 'text' {
    const t = (m?.message_type || '').trim();
    if (['image','video','audio','file','sticker','text'].includes(t)) return t as any;
    const mime = (m?.content_mime || '').toLowerCase();
    if (mime.startsWith('image/')) return 'image';
    if (mime.startsWith('video/')) return 'video';
    if (mime.startsWith('audio/')) return 'audio';
    if (m?.content_url)            return 'file';
    return 'text';
  }

  bodyText(m: any): string {
    return (m?.text || '').toString();
  }

  // ── 媒體 ─────────────────────────────────────────────────

  mediaSrc(m: any): string | null {
    const url = (m?.content_url || '').trim();
    if (!url) return null;
    const key = (m?.line_message_id || m?.id || url).toString();
    if (this.mediaCache.has(key)) return this.mediaCache.get(key)!;
    if (!this.mediaLoading.has(key)) {
      this.mediaLoading.add(key);
      this.fetchAsBlobUrl(url, key);
    }
    return null;
  }

  private async fetchAsBlobUrl(url: string, key: string) {
    try {
      const token  = localStorage.getItem('ADMIN_TOKEN') || '';
      const res    = await fetch(url, { headers: { 'X-Admin-Token': token } });
      if (!res.ok) throw new Error(`fetch media failed ${res.status}`);
      const objUrl = URL.createObjectURL(await res.blob());
      this.mediaCache.set(key, objUrl);
    } catch (e) {
      console.error('fetchAsBlobUrl failed', e);
    } finally {
      this.mediaLoading.delete(key);
    }
  }

  download(m: any) {
    const url  = (m?.content_url || '').trim();
    const name = (m?.content_name || 'download').toString();
    if (!url) return;
    const key    = `dl:${m?.line_message_id || m?.id || url}`;
    const doSave = (src: string) => {
      const a = document.createElement('a'); a.href = src; a.download = name; a.click();
    };
    const cached = this.mediaCache.get(key);
    if (cached) { doSave(cached); return; }
    this.fetchAsBlobUrl(url, key).then(() => {
      const s = this.mediaCache.get(key); if (s) doSave(s);
    });
  }

  stickerSrc(m: any): string | null {
    if (m?.sticker_url) return m.sticker_url;
    if (m?.package_id && m?.sticker_id)
      return `https://stickershop.line-scdn.net/stickershop/v1/sticker/${m.sticker_id}/iPhone/sticker.png`;
    return null;
  }

  // ── Viewer ────────────────────────────────────────────────

  openViewer(m: any) {
    const src = this.mediaSrc(m);
    if (!src) return;
    this.viewerSrc  = src;
    this.viewerName = (m?.content_name || m?.line_message_id || 'image').toString();
    this.viewerOpen = true;
  }

  closeViewer() {
    this.viewerOpen = false;
    this.viewerSrc  = '';
    this.viewerName = '';
  }

  // ── 工具 ─────────────────────────────────────────────────

  onAvatarError(m: any) {
    m.sender_picture_url = null; 
    m.picture_url = null; 
  }

  getPictureUrl(m: any): string | null {
    // 相容各種欄位名稱（含空格版本）
    return m.sender_picture_url
        || m['sender picture url']
        || m.picture_url
        || m.user_picture_url
        || null;
  }
  
  onImageError(ev: Event) {
    (ev.target as HTMLImageElement).style.display = 'none'; 
  }

  formatTime(iso: string): string {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' });
  }

  formatDate(iso: string): string {
    if (!iso) return '';
    const d = new Date(iso);
    return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`;
  }

  get statusColor(): string { return SESSION_STATUS_COLOR[this.currentStatus] ?? '#9E9E9E'; }
  get statusLabel(): string { return SESSION_STATUS_LABEL[this.currentStatus] ?? this.currentStatus; }

  trackById(_: number, m: TicketMessage) { return m.id; }
  trackNoteById(_: number, n: CustomerNote) { return n.id; }
}
