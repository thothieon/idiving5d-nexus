import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AdminApiService } from '../../Service/api/admin-api.service';
import { AdminTokenService } from '../../Service/auth/admin-token.service';
import {
  RegCourse, RegCourseForm, RegSession, RegSessionForm, RegRegistration, RegCustomerUpdate
} from '../../Service/api/models';

type PageTab = 'registrations' | 'sessions' | 'courses';

@Component({
  standalone: true,
  selector: 'app-registration',
  imports: [CommonModule, FormsModule],
  templateUrl: './registration.component.html',
  styleUrl: './registration.component.scss',
})
export class RegistrationComponent implements OnInit {

  pageTab: PageTab = 'registrations';

  // ── 共用 ──────────────────────────────────────────────────
  courses: RegCourse[] = [];
  successMsg = '';
  errorMsg   = '';

  // ── 報名名單 ──────────────────────────────────────────────
  registrations: RegRegistration[] = [];
  loadingRegs    = false;
  filterCourseId: number | '' = '';
  filterSessionId: number | '' = '';
  filterStatus    = '';
  filteredSessions: RegSession[] = [];

  // 詳情/操作 dialog
  selectedReg: RegRegistration | null = null;
  updatingReg  = false;
  updateError  = '';

  // 編輯客戶資料
  editingCustomer  = false;
  customerDraft: RegCustomerUpdate = {};
  savingCustomer   = false;
  customerSaveErr  = '';
  readonly bloodTypes = ['A', 'B', 'O', 'AB', 'A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-'];

  // ── 課程設定 ──────────────────────────────────────────────
  showCourseForm  = false;
  editingCourseId: number | null = null;
  courseDraft: RegCourseForm = this.emptyCourse();
  savingCourse    = false;
  courseFormError = '';

  // ── 梯次管理 ──────────────────────────────────────────────
  sessions: RegSession[] = [];
  loadingSessions = false;

  showSessionForm  = false;
  editingSessionId: number | null = null;
  sessionDraft: RegSessionForm = this.emptySession();
  savingSession    = false;
  sessionFormError = '';

  readonly statusOptions = [
    { value: '',           label: '全部狀態' },
    { value: 'pending',    label: '待確認' },
    { value: 'confirmed',  label: '已確認' },
    { value: 'waitlist',   label: '候補' },
    { value: 'cancelled',  label: '已取消' },
  ];

  readonly statusLabel: Record<string, string> = {
    pending:   '待確認',
    confirmed: '已確認',
    cancelled: '已取消',
    waitlist:  '候補',
  };

  readonly paymentLabel: Record<string, string> = {
    unpaid: '未付款',
    paid:   '已付款',
  };

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
    this.loadCourses();
  }

  // ── 課程載入 ──────────────────────────────────────────────

  loadCourses() {
    this.api.regListCourses().subscribe({
      next: (list) => {
        this.courses = list;
        this.cdr.detectChanges();
        this.loadRegistrations();
        this.loadSessions();
      },
      error: () => { this.errorMsg = '載入課程失敗'; this.cdr.detectChanges(); }
    });
  }

  // ── 報名名單 ──────────────────────────────────────────────

  loadRegistrations() {
    this.loadingRegs = true;
    this.errorMsg    = '';
    const params: any = {};
    if (this.filterCourseId)  params.course_id  = this.filterCourseId;
    if (this.filterSessionId) params.session_id = this.filterSessionId;
    if (this.filterStatus)    params.reg_status  = this.filterStatus;

    this.api.regListRegistrations(params).subscribe({
      next: (list) => {
        this.registrations = list;
        this.loadingRegs   = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.errorMsg    = '載入報名名單失敗';
        this.loadingRegs = false;
        this.cdr.detectChanges();
      }
    });
  }

  onCourseFilterChange() {
    this.filterSessionId = '';
    // 更新梯次下拉選單
    if (this.filterCourseId) {
      this.filteredSessions = this.sessions.filter(
        s => s.course_id === Number(this.filterCourseId)
      );
    } else {
      this.filteredSessions = this.sessions;
    }
    this.loadRegistrations();
  }

  openRegDetail(reg: RegRegistration) {
    this.selectedReg    = { ...reg };
    this.updateError    = '';
    this.updatingReg    = false;
    this.editingCustomer = false;
    this.customerDraft  = {};
    this.customerSaveErr = '';
  }

  closeRegDetail() {
    this.selectedReg     = null;
    this.editingCustomer = false;
  }

  startEditCustomer() {
    if (!this.selectedReg) return;
    const r = this.selectedReg;
    this.customerDraft = {
      name: r.name, phone: r.phone, home_phone: r.home_phone,
      email: r.email, mid: r.mid,
      nickname: r.nickname, name_en: r.name_en,
      birth_date: r.birth_date, nationality: r.nationality, blood_type: r.blood_type,
      address: r.address, emergency_contact: r.emergency_contact, emergency_phone: r.emergency_phone,
      height: r.height, weight: r.weight,
      vision_left: r.vision_left, vision_right: r.vision_right,
      payment_date: r.payment_date, membership_expiry: r.membership_expiry,
    };
    this.editingCustomer = true;
    this.customerSaveErr  = '';
  }

  saveCustomer() {
    if (!this.selectedReg || this.savingCustomer) return;
    this.savingCustomer  = true;
    this.customerSaveErr = '';
    this.api.regUpdateCustomer(this.selectedReg.customer_id, this.customerDraft).subscribe({
      next: () => {
        // 更新 selectedReg 顯示
        Object.assign(this.selectedReg!, this.customerDraft);
        this.savingCustomer  = false;
        this.editingCustomer = false;
        this.flash('✓ 客戶資料已儲存');
        this.loadRegistrations();
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.savingCustomer  = false;
        this.customerSaveErr = err.error?.detail || '儲存失敗';
        this.cdr.detectChanges();
      }
    });
  }

  updateRegStatus(status: string) {
    if (!this.selectedReg) return;
    this.updatingReg = true;
    this.updateError = '';

    this.api.regUpdateRegistration(this.selectedReg.id, { reg_status: status }).subscribe({
      next: () => {
        this.flash('✓ 狀態已更新');
        this.selectedReg = null;
        this.updatingReg = false;
        this.loadRegistrations();
      },
      error: (err) => {
        this.updateError = err.error?.detail || '更新失敗';
        this.updatingReg = false;
        this.cdr.detectChanges();
      }
    });
  }

  updatePaymentStatus(status: string) {
    if (!this.selectedReg) return;
    this.updatingReg = true;
    this.updateError = '';

    this.api.regUpdateRegistration(this.selectedReg.id, { payment_status: status }).subscribe({
      next: () => {
        this.flash('✓ 付款狀態已更新');
        this.selectedReg = null;
        this.updatingReg = false;
        this.loadRegistrations();
      },
      error: (err) => {
        this.updateError = err.error?.detail || '更新失敗';
        this.updatingReg = false;
        this.cdr.detectChanges();
      }
    });
  }

  exportExcel() {
    const params: any = {};
    if (this.filterCourseId)  params.course_id  = this.filterCourseId;
    if (this.filterSessionId) params.session_id = this.filterSessionId;
    if (this.filterStatus)    params.reg_status  = this.filterStatus;
    window.open(this.api.regExportUrl(params), '_blank');
  }

  // ── 梯次管理 ──────────────────────────────────────────────

  loadSessions() {
    this.loadingSessions = true;
    this.api.regListSessions().subscribe({
      next: (list) => {
        this.sessions        = list;
        this.filteredSessions = list;
        this.loadingSessions = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.errorMsg        = '載入梯次失敗';
        this.loadingSessions = false;
        this.cdr.detectChanges();
      }
    });
  }

  openCreateSession() {
    this.editingSessionId = null;
    this.sessionDraft     = this.emptySession();
    this.sessionFormError = '';
    this.showSessionForm  = true;
  }

  openEditSession(s: RegSession) {
    this.editingSessionId = s.id;
    this.sessionDraft = {
      course_id:         s.course_id,
      label:             s.label,
      start_date:        s.start_date,
      end_date:          s.end_date,
      capacity:          s.capacity,
      waitlist_capacity: s.waitlist_capacity,
      status:            s.status,
      note:              s.note ?? '',
    };
    this.sessionFormError = '';
    this.showSessionForm  = true;
  }

  saveSession() {
    if (!this.sessionDraft.course_id || !this.sessionDraft.label ||
        !this.sessionDraft.start_date || !this.sessionDraft.end_date) {
      this.sessionFormError = '課程、名稱、日期為必填';
      return;
    }
    this.savingSession    = true;
    this.sessionFormError = '';

    const obs = this.editingSessionId
      ? this.api.regUpdateSession(this.editingSessionId, this.sessionDraft)
      : this.api.regCreateSession(this.sessionDraft);

    obs.subscribe({
      next: () => {
        this.flash(this.editingSessionId ? '✓ 梯次已更新' : '✓ 梯次已新增');
        this.showSessionForm  = false;
        this.savingSession    = false;
        this.loadSessions();
      },
      error: (err) => {
        this.sessionFormError = err.error?.detail || '儲存失敗';
        this.savingSession    = false;
        this.cdr.detectChanges();
      }
    });
  }

  toggleSessionStatus(s: RegSession) {
    const newStatus = s.status === 'open' ? 'closed' : 'open';
    this.api.regUpdateSession(s.id, { status: newStatus }).subscribe({
      next: () => {
        this.flash(`✓ 梯次已${newStatus === 'open' ? '開啟' : '關閉'}`);
        this.loadSessions();
      },
      error: () => { this.errorMsg = '操作失敗'; this.cdr.detectChanges(); }
    });
  }

  // ── 工具 ──────────────────────────────────────────────────

  // ── 課程管理 ──────────────────────────────────────────────

  openCreateCourse() {
    this.editingCourseId = null;
    this.courseDraft     = this.emptyCourse();
    this.courseFormError = '';
    this.showCourseForm  = true;
  }

  openEditCourse(c: RegCourse) {
    this.editingCourseId = c.id;
    this.courseDraft = {
      course_code:  c.course_code,
      title:        c.title,
      type:         c.type,
      description:  (c as any).description ?? '',
      require_form: c.require_form,
      is_active:    c.is_active,
      sort_order:   (c as any).sort_order ?? 0,
    };
    this.courseFormError = '';
    this.showCourseForm  = true;
  }

  saveCourse() {
    if (!this.courseDraft.course_code.trim() || !this.courseDraft.title.trim()) {
      this.courseFormError = '代碼與名稱為必填';
      return;
    }
    this.savingCourse    = true;
    this.courseFormError = '';

    const obs = this.editingCourseId
      ? this.api.regUpdateCourse(this.editingCourseId, this.courseDraft)
      : this.api.regCreateCourse(this.courseDraft);

    obs.subscribe({
      next: () => {
        this.flash(this.editingCourseId ? '✓ 課程已更新' : '✓ 課程已新增');
        this.showCourseForm = false;
        this.savingCourse   = false;
        this.loadCourses();
      },
      error: (err) => {
        this.courseFormError = err.error?.detail || '儲存失敗';
        this.savingCourse    = false;
        this.cdr.detectChanges();
      }
    });
  }

  toggleCourseActive(c: RegCourse) {
    const newVal = c.is_active ? 0 : 1;
    this.api.regUpdateCourse(c.id, { is_active: newVal }).subscribe({
      next: () => {
        this.flash(`✓ 課程已${newVal ? '上架' : '下架'}`);
        this.loadCourses();
      },
      error: () => { this.errorMsg = '操作失敗'; this.cdr.detectChanges(); }
    });
  }

  emptyCourse(): RegCourseForm {
    return {
      course_code: '', title: '', type: 'course',
      description: '', require_form: 0, is_active: 1, sort_order: 0,
    };
  }

  emptySession(): RegSessionForm {
    return {
      course_id: 0, label: '', start_date: '', end_date: '',
      capacity: 8, waitlist_capacity: 0, status: 'open', note: '',
    };
  }

  flash(msg: string) {
    this.successMsg = msg;
    this.cdr.detectChanges();
    setTimeout(() => { this.successMsg = ''; this.cdr.detectChanges(); }, 3000);
  }

  courseName(id: number): string {
    return this.courses.find(c => c.id === id)?.title ?? '';
  }

  goBack() {
    this.router.navigateByUrl('/admin/turn');
  }
}
