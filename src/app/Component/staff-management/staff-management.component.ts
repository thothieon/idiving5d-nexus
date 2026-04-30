import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import { StaffItem, StaffPermissions } from '../../Service/api/models';

export const PERMISSION_KEYS: { key: keyof StaffPermissions; label: string }[] = [
  { key: 'can_registration', label: '報名管理' },
  { key: 'can_courses',      label: '課程管理' },
  { key: 'can_pagestats',    label: '頁面統計' },
  { key: 'can_linestats',    label: 'LINE 統計' },
  { key: 'can_questions',    label: '常見問題' },
  { key: 'can_quickreply',   label: '快速回覆' },
];

interface StaffForm {
  name:        string;
  username:    string;
  password:    string;
  role:        'admin' | 'staff';
  email:       string;
  permissions: StaffPermissions;
}

@Component({
  standalone: true,
  selector: 'app-staff-management',
  imports: [CommonModule, FormsModule],
  templateUrl: './staff-management.component.html',
  styleUrl: './staff-management.component.scss',
})
export class StaffManagementComponent implements OnInit {
  items: StaffItem[] = [];
  loading  = false;
  errorMsg = '';

  readonly permKeys = PERMISSION_KEYS;

  // 新增員工 Panel
  showCreate = false;
  creating   = false;
  createErr  = '';
  createForm: StaffForm = this.emptyForm();

  // 編輯員工 Panel
  editTarget: StaffItem | null = null;
  editForm: Partial<StaffForm> = {};
  editing   = false;
  editErr   = '';

  // 改密碼 Panel
  pwTarget: StaffItem | null = null;
  newPassword = '';
  pwSaving    = false;
  pwErr       = '';

  constructor(
    private api: AdminApiService,
    private tokenSvc: AdminTokenService,
    private router: Router,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit() {
    if (!this.tokenSvc.isAdmin()) {
      this.router.navigateByUrl('/admin/turn');
      return;
    }
    this.load();
  }

  load() {
    this.loading = true;
    this.errorMsg = '';
    this.api.staffList().subscribe({
      next: (items) => { this.items = items; this.loading = false; this.cdr.detectChanges(); },
      error: (err)  => {
        this.loading = false;
        if (err?.status === 401) {
          this.tokenSvc.clear();
          this.router.navigateByUrl('/admin/login');
          return;
        }
        this.errorMsg = err?.error?.detail ?? '讀取失敗';
        this.cdr.detectChanges();
      },
    });
  }

  // ── 新增 ──────────────────────────────────────────────────

  emptyForm(): StaffForm {
    const perms: StaffPermissions = {};
    for (const p of PERMISSION_KEYS) perms[p.key] = false;
    return { name: '', username: '', password: '', role: 'staff', email: '', permissions: perms };
  }

  defaultPerms(): StaffPermissions {
    const perms: StaffPermissions = {};
    for (const p of PERMISSION_KEYS) perms[p.key] = false;
    return perms;
  }

  openCreate() {
    this.createForm = this.emptyForm();
    this.createErr  = '';
    this.showCreate = true;
  }

  submitCreate() {
    this.createErr = '';
    const { name, username, password, role, email, permissions } = this.createForm;
    if (!name.trim() || !username.trim() || !password.trim()) {
      this.createErr = '姓名、帳號、密碼不可空白'; return;
    }
    if (password.length < 6) { this.createErr = '密碼至少 6 個字元'; return; }

    const perms = role === 'admin' ? null : permissions;
    this.creating = true;
    this.api.staffCreate({ name: name.trim(), username: username.trim(), password, role, email: email.trim() || null, permissions: perms }).subscribe({
      next: () => { this.creating = false; this.showCreate = false; this.cdr.detectChanges(); this.load(); },
      error: (err) => {
        this.creating = false;
        if (err?.status === 401) { this.tokenSvc.clear(); this.router.navigateByUrl('/admin/login'); return; }
        this.createErr = err?.error?.detail ?? '新增失敗';
        this.cdr.detectChanges();
      },
    });
  }

  // ── 編輯 ──────────────────────────────────────────────────

  openEdit(item: StaffItem) {
    this.editTarget = item;
    const perms: StaffPermissions = {};
    for (const p of PERMISSION_KEYS) {
      perms[p.key] = item.permissions?.[p.key] ?? false;
    }
    this.editForm = { name: item.name, username: item.username ?? '', role: item.role, email: item.email ?? '', permissions: perms };
    this.editErr  = '';
  }

  submitEdit() {
    if (!this.editTarget) return;
    this.editErr = '';
    const { name, username, role, email, permissions } = this.editForm;
    if (!name?.trim() || !username?.trim()) { this.editErr = '姓名與帳號不可空白'; return; }

    const perms = role === 'admin' ? null : permissions;
    this.editing = true;
    this.api.staffUpdate(this.editTarget.id, { name: name.trim(), username: username.trim(), role, email: (email ?? '').trim() || null, permissions: perms }).subscribe({
      next: () => { this.editing = false; this.editTarget = null; this.cdr.detectChanges(); this.load(); },
      error: (err) => {
        this.editing = false;
        if (err?.status === 401) { this.tokenSvc.clear(); this.router.navigateByUrl('/admin/login'); return; }
        this.editErr = err?.error?.detail ?? '更新失敗';
        this.cdr.detectChanges();
      },
    });
  }

  // ── 刪除 ──────────────────────────────────────────────────

  deleteStaff(item: StaffItem) {
    if (!confirm(`確定刪除「${item.name}」的帳號？此操作無法復原。`)) return;
    this.api.staffDelete(item.id).subscribe({
      next: () => { this.load(); },
      error: (err) => { this.errorMsg = err?.error?.detail ?? '刪除失敗'; this.cdr.detectChanges(); },
    });
  }

  // ── 改密碼 ────────────────────────────────────────────────

  openPassword(item: StaffItem) {
    this.pwTarget   = item;
    this.newPassword = '';
    this.pwErr      = '';
  }

  submitPassword() {
    if (!this.pwTarget) return;
    this.pwErr = '';
    if (this.newPassword.length < 6) { this.pwErr = '密碼至少 6 個字元'; return; }

    this.pwSaving = true;
    this.api.staffSetPassword(this.pwTarget.id, this.newPassword).subscribe({
      next: () => { this.pwSaving = false; this.pwTarget = null; this.cdr.detectChanges(); },
      error: (err) => {
        this.pwSaving = false;
        if (err?.status === 401) { this.tokenSvc.clear(); this.router.navigateByUrl('/admin/login'); return; }
        this.pwErr = err?.error?.detail ?? '設定失敗';
        this.cdr.detectChanges();
      },
    });
  }

  back() {
    this.router.navigateByUrl('/admin/turn');
  }

  roleLabel(role: string) { return role === 'admin' ? '管理者' : '客服'; }

  permSummary(item: StaffItem): string {
    if (item.role === 'admin') return '全部';
    if (!item.permissions) return '全部';
    const granted = PERMISSION_KEYS.filter(p => item.permissions![p.key]).map(p => p.label);
    return granted.length ? granted.join('、') : '無';
  }
}
