import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import { CourseSchedule, CourseScheduleForm } from '../../Service/api/models';

const COURSE_OPTIONS = [
  { code: 'DPV',  name: 'DPV 推進器',  color: '#1e90ff' },
  { code: 'RSM',  name: 'RSM 側掛',    color: '#e65100' },
  { code: 'DRY',  name: 'DRY 乾衣',    color: '#6a1b9a' },
  { code: 'DECO', name: 'DECO 減壓',   color: '#2e7d32' },
];

@Component({
  standalone: true,
  selector: 'app-course-schedule',
  imports: [CommonModule, FormsModule],
  templateUrl: './course-schedule.component.html',
  styleUrl: './course-schedule.component.scss',
})
export class CourseScheduleComponent implements OnInit {
  schedules: CourseSchedule[] = [];
  loading = true;
  errorMsg = '';
  successMsg = '';

  // 分組（依 course_code）
  groups: { code: string; name: string; color: string; items: CourseSchedule[] }[] = [];

  // 新增/編輯表單
  showForm = false;
  editingId: number | null = null;
  draft: CourseScheduleForm = this.emptyDraft();
  saving = false;
  formError = '';

  // 刪除確認
  confirmDeleteId: number | null = null;

  readonly courseOptions = COURSE_OPTIONS;

  constructor(
    private api: AdminApiService,
    private tokenSvc: AdminTokenService,
    private router: Router,
    private cdr: ChangeDetectorRef,
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
    this.api.listCourseSchedules().subscribe({
      next: (items) => {
        this.schedules = items;
        this.buildGroups(items);
        this.loading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loading = false;
        this.errorMsg = '讀取失敗';
        this.cdr.detectChanges();
      },
    });
  }

  private buildGroups(items: CourseSchedule[]) {
    this.groups = COURSE_OPTIONS.map(opt => ({
      ...opt,
      items: items.filter(s => s.course_code === opt.code),
    }));
  }

  goBack() {
    this.router.navigateByUrl('/admin/turn');
  }

  // ── 表單開關 ──────────────────────────────────────────────

  openCreate(code?: string) {
    this.editingId = null;
    this.draft = this.emptyDraft();
    if (code) {
      const opt = COURSE_OPTIONS.find(o => o.code === code);
      if (opt) {
        this.draft.course_code = opt.code;
        this.draft.course_name = opt.name + ' 開課';
        this.draft.color = opt.color;
      }
    }
    this.formError = '';
    this.showForm = true;
  }

  openEdit(s: CourseSchedule) {
    this.editingId = s.id;
    this.draft = {
      course_code: s.course_code,
      course_name: s.course_name,
      start_date:  s.start_date,
      end_date:    s.end_date,
      color:       s.color,
      note:        s.note ?? '',
      is_active:   s.is_active,
    };
    this.formError = '';
    this.showForm = true;
  }

  closeForm() {
    this.showForm = false;
  }

  // ── 當選課程代碼改變時，自動帶入預設名稱和顏色 ─────────────

  onCourseCodeChange() {
    const opt = COURSE_OPTIONS.find(o => o.code === this.draft.course_code);
    if (opt && !this.editingId) {
      this.draft.course_name = opt.name + ' 開課';
      this.draft.color = opt.color;
    }
  }

  // ── 儲存 ──────────────────────────────────────────────────

  save() {
    this.formError = '';
    if (!this.draft.course_code.trim()) { this.formError = '請選擇課程'; return; }
    if (!this.draft.course_name.trim()) { this.formError = '課程名稱不能為空'; return; }
    if (!this.draft.start_date)         { this.formError = '請選擇開課日'; return; }
    if (!this.draft.end_date)           { this.formError = '請選擇結課日'; return; }
    if (this.draft.start_date > this.draft.end_date) {
      this.formError = '結課日不能早於開課日';
      return;
    }

    const payload: CourseScheduleForm = {
      course_code: this.draft.course_code.trim(),
      course_name: this.draft.course_name.trim(),
      start_date:  this.draft.start_date,
      end_date:    this.draft.end_date,
      color:       this.draft.color || '#1e90ff',
      note:        this.draft.note?.trim() ?? '',
      is_active:   this.draft.is_active,
    };

    this.saving = true;
    const req$ = this.editingId !== null
      ? this.api.updateCourseSchedule(this.editingId, payload)
      : this.api.createCourseSchedule(payload);

    req$.subscribe({
      next: () => {
        this.saving = false;
        this.showForm = false;
        this.flash('儲存成功');
        this.cdr.detectChanges();
        this.load();
      },
      error: (e) => {
        this.saving = false;
        this.formError = e?.error?.detail ?? '儲存失敗';
        this.cdr.detectChanges();
      },
    });
  }

  // ── 切換顯示/隱藏 ─────────────────────────────────────────

  toggleActive(s: CourseSchedule) {
    const newVal = s.is_active ? 0 : 1;
    this.api.updateCourseSchedule(s.id, { is_active: newVal }).subscribe({
      next: () => { s.is_active = newVal; this.cdr.detectChanges(); },
      error: () => { this.flash('切換失敗', true); this.cdr.detectChanges(); },
    });
  }

  // ── 刪除 ──────────────────────────────────────────────────

  askDelete(id: number) { this.confirmDeleteId = id; }
  cancelDelete()        { this.confirmDeleteId = null; }

  confirmDelete() {
    if (this.confirmDeleteId === null) return;
    const id = this.confirmDeleteId;
    this.confirmDeleteId = null;
    this.api.deleteCourseSchedule(id).subscribe({
      next: () => { this.flash('已刪除'); this.load(); },
      error: () => { this.flash('刪除失敗', true); },
    });
  }

  // ── 工具 ──────────────────────────────────────────────────

  private emptyDraft(): CourseScheduleForm {
    return {
      course_code: '',
      course_name: '',
      start_date:  '',
      end_date:    '',
      color:       '#1e90ff',
      note:        '',
      is_active:   1,
    };
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
