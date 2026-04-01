import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { timeout, TimeoutError } from 'rxjs';
import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';

interface QuestionItem {
  phrase: string;
  count: number;
}

@Component({
  standalone: true,
  selector: 'app-questions-stats',
  imports: [CommonModule],
  templateUrl: './questions-stats.component.html',
  styleUrl: './questions-stats.component.scss',
})
export class QuestionsStatsComponent implements OnInit {
  days = 7;
  items: QuestionItem[] = [];
  loading = false;
  errorMsg = '';

  readonly dayOptions = [7, 14, 30];

  constructor(
    private api: AdminApiService,
    private tokenSvc: AdminTokenService,
    private router: Router,
  ) {}

  ngOnInit() {
    if (!this.tokenSvc.isAdmin()) {
      this.router.navigateByUrl('/admin/turn');
      return;
    }
    this.load();
  }

  setDays(d: number) {
    if (this.days === d) return;
    this.days = d;
    this.load();
  }

  load() {
    this.loading = true;
    this.errorMsg = '';
    this.api.statsQuestions(this.days).pipe(
      timeout(30000),
    ).subscribe({
      next: (res) => {
        this.items = res?.items ?? [];
        this.loading = false;
      },
      error: (err) => {
        this.loading = false;
        if (err instanceof TimeoutError) {
          this.errorMsg = '查詢逾時（資料量過大），請稍後再試';
          return;
        }
        if (err?.status === 401) {
          this.tokenSvc.clear();
          this.router.navigateByUrl('/admin/login');
          return;
        }
        this.errorMsg = err?.error?.detail ?? '讀取失敗';
      },
    });
  }

  back() {
    this.router.navigateByUrl('/admin/turn');
  }

  get maxCount(): number {
    return this.items[0]?.count ?? 1;
  }
}
