import { Component, OnInit, DestroyRef, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { interval, of } from 'rxjs';
import { catchError, startWith, switchMap, tap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import { TicketMessage } from '../../Service/api/models';

@Component({
  standalone: true,
  selector: 'app-ticket-detail',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './ticket-detail.component.html',
  styleUrl: './ticket-detail.component.scss',
})
export class TicketDetailComponent implements OnInit {
  ticketId = 0;

  loading = false;
  sending = false;
  errorMsg = '';

  items: any[] = [];
  draft = '';

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private api: AdminApiService,
    private tokenSvc: AdminTokenService,
  ) {}

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

    this.refresh();
  }

  refresh() {
    this.loading = true;
    this.errorMsg = '';

    this.api.getMessages(this.ticketId, 200).subscribe({
      next: (rows) => {
        this.items = rows || [];
        this.loading = false;
        // 你若想自動捲到底：可在這裡加 scrollIntoView（之後我也能幫你補）
      },
      error: () => {
        this.loading = false;
        this.errorMsg = '讀取訊息失敗（可能 token 失效或 API 無法連線）';
        this.router.navigateByUrl('/admin/login');
      },
    });
  }

  send() {
    const text = (this.draft || '').trim();
    if (!text || this.sending) return;

    // 先把輸入框清掉（視覺上立刻清空）
    this.draft = '';

    this.sending = true;
    this.errorMsg = '';

    this.api.reply(this.ticketId, text).subscribe({
      next: () => {
        // 成功：維持清空，並刷新訊息
        this.draft = '';
        this.sending = false;
        this.refresh();
      },
      error: (err) => {
        this.sending = false;
      
        // 失敗：把剛剛要送的文字還回輸入框，避免使用者白打
        this.draft = text;

        // 把後端回的 error 顯示出來（超重要）
        const backend = err?.error?.error || err?.error?.message;
        this.errorMsg = backend || `送出失敗（HTTP ${err?.status || '??'}）`;
        console.log('reply error', err);
      },
    });
  }

  close() {
    if (!confirm('確定要結案？')) return;

    this.api.close(this.ticketId).subscribe({
      next: () => this.router.navigateByUrl('/admin/turn'),
      error: () => (this.errorMsg = '結案失敗'),
    });
  }

  // content_url > sticker_url > text
  bodyType(m: any): 'image' | 'text' {
    const u = this.bodyImage(m);
    return u ? 'image' : 'text';
  }

  bodyImage(m: any): string | null {
    const content = (m?.content_url || '').trim();
    if (content) return content;

    const sticker = (m?.sticker_url || '').trim();
    if (sticker) return sticker;

    return null;
  }

  onAvatarError(m: any) {
    m.sender_picture_url = null;
  }

  onImageError(ev: Event) {
    // 圖片壞掉不要一直刷
    (ev.target as HTMLImageElement).style.display = 'none';
  }
}
