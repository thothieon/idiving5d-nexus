import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminApiService } from '../../Service/api/admin-api.service';
import { CustomerListItem, CustomerDetail, CustomerRegHistory, RegCustomerUpdate } from '../../Service/api/models';

@Component({
  selector: 'app-customer-management',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './customer-management.component.html',
  styleUrl: './customer-management.component.scss',
})
export class CustomerManagementComponent implements OnInit {

  // ── 列表 ──────────────────────────────────────────────────
  customers: CustomerListItem[] = [];
  total     = 0;
  loading   = false;
  errorMsg  = '';

  searchQ   = '';
  page      = 0;
  pageSize  = 30;

  // ── 詳細 ──────────────────────────────────────────────────
  selected:      CustomerDetail | null = null;
  selectedRegs:  CustomerRegHistory[]  = [];
  loadingDetail  = false;

  // ── 編輯 ──────────────────────────────────────────────────
  editMode  = false;
  editForm: Partial<RegCustomerUpdate> = {};
  saving    = false;
  saveError = '';
  successMsg = '';

  readonly today = new Date().toISOString().split('T')[0];

  readonly statusLabel: Record<string, string> = {
    pending:          '待確認',
    data_confirmed:   '待付款',
    payment_submitted:'已匯款',
    confirmed:        '已完成',
    cancelled:        '已取消',
    waitlist:         '候補',
  };

  constructor(private api: AdminApiService, private cdr: ChangeDetectorRef) {}

  ngOnInit() { this.loadList(); }

  loadList() {
    this.loading  = true;
    this.errorMsg = '';
    this.api.customerList(this.searchQ, this.page * this.pageSize, this.pageSize).subscribe({
      next: r => {
        this.customers = r.items;
        this.total     = r.total;
        this.loading   = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.errorMsg = '載入失敗，請稍後再試';
        this.loading  = false;
        this.cdr.detectChanges();
      }
    });
  }

  onSearch() { this.page = 0; this.loadList(); }

  prevPage() { if (this.page > 0) { this.page--; this.loadList(); } }
  nextPage() { if ((this.page + 1) * this.pageSize < this.total) { this.page++; this.loadList(); } }
  get totalPages() { return Math.ceil(this.total / this.pageSize); }

  openDetail(c: CustomerListItem) {
    this.selected      = null;
    this.selectedRegs  = [];
    this.editMode      = false;
    this.loadingDetail = true;
    this.api.customerGet(c.id).subscribe({
      next: r => {
        this.selected     = r.customer;
        this.selectedRegs = r.registrations;
        this.loadingDetail = false;
        this.cdr.detectChanges();
      },
      error: () => { this.loadingDetail = false; this.cdr.detectChanges(); }
    });
  }

  closeDetail() { this.selected = null; this.editMode = false; }

  startEdit() {
    if (!this.selected) return;
    const c = this.selected;
    this.editForm = {
      name: c.name, phone: c.phone, home_phone: c.home_phone,
      email: c.email, mid: c.mid, nickname: c.nickname,
      name_en: c.name_en, birth_date: c.birth_date,
      nationality: c.nationality, blood_type: c.blood_type,
      address: c.address,
      emergency_contact: c.emergency_contact, emergency_phone: c.emergency_phone,
      height: c.height ?? undefined, weight: c.weight ?? undefined,
      shoe_size: c.shoe_size ?? undefined,
      vision_left: c.vision_left ?? undefined, vision_right: c.vision_right ?? undefined,
      payment_date: c.payment_date, membership_expiry: c.membership_expiry,
    };
    this.saveError = '';
    this.editMode  = true;
  }

  saveEdit() {
    if (!this.selected) return;
    this.saving    = true;
    this.saveError = '';
    this.api.customerUpdate(this.selected.id, this.editForm).subscribe({
      next: () => {
        this.saving   = false;
        this.editMode = false;
        this.flash('✓ 儲存成功');
        this.openDetail({ id: this.selected!.id } as any);
        this.loadList();
      },
      error: err => {
        this.saveError = err.error?.detail || '儲存失敗';
        this.saving    = false;
        this.cdr.detectChanges();
      }
    });
  }

  flash(msg: string) {
    this.successMsg = msg;
    setTimeout(() => { this.successMsg = ''; this.cdr.detectChanges(); }, 3000);
  }

  age(birthDate: string | null): string {
    if (!birthDate) return '—';
    const diff = Date.now() - new Date(birthDate).getTime();
    return String(Math.floor(diff / (1000 * 60 * 60 * 24 * 365.25))) + ' 歲';
  }
}
