// admin-api.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { map } from 'rxjs/operators';
import { Observable } from 'rxjs';

import {
  TicketMessage, TicketListItem,
  TicketStatusResponse, SessionHistory,
  Booking, BookingForm, CustomerNote,
  QuickReplyRule, QuickReplyButton,
  StaffItem, Tag,
  CourseSchedule, CourseScheduleForm,
} from './models';

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private base = '/admin/api';

  constructor(private http: HttpClient) {}

  // ── 認證 ──────────────────────────────────────────────────

  login(username: string, password: string) {
    return this.http.post<{ ok: boolean; token: string; name: string; role: string }>(
      `${this.base}/auth/login`,
      { username, password },
    );
  }

  logout() {
    return this.http.post<any>(`${this.base}/auth/logout`, {});
  }

  // ── 員工管理（admin only）────────────────────────────────

  staffList() {
    return this.http.get<{ ok: boolean; items: StaffItem[] }>(
      `${this.base}/staff`
    ).pipe(map(r => r.items));
  }

  staffCreate(body: { name: string; username: string; password: string; role: string }) {
    return this.http.post<{ ok: boolean; id: number }>(`${this.base}/staff`, body);
  }

  staffUpdate(id: number, body: { name?: string; username?: string; role?: string; is_active?: number }) {
    return this.http.patch<{ ok: boolean }>(`${this.base}/staff/${id}`, body);
  }

  staffSetPassword(id: number, password: string) {
    return this.http.post<{ ok: boolean }>(`${this.base}/staff/${id}/set-password`, { password });
  }

  staffDelete(id: number) {
    return this.http.delete<{ ok: boolean }>(`${this.base}/staff/${id}`);
  }

  // ── 客戶標籤 ─────────────────────────────────────────────
  listTags(): Observable<Tag[]> {
    return this.http.get<any>(`${this.base}/tags`).pipe(map(r => r.items ?? []));
  }

  createTag(body: { name: string; color: string }): Observable<any> {
    return this.http.post<any>(`${this.base}/tags`, body);
  }

  deleteTag(tagId: number): Observable<any> {
    return this.http.delete<any>(`${this.base}/tags/${tagId}`);
  }

  getCustomerTags(customerId: number): Observable<Tag[]> {
    return this.http.get<any>(`${this.base}/customers/${customerId}/tags`).pipe(map(r => r.items ?? []));
  }

  updateCustomerName(customerId: number, name: string | null): Observable<any> {
    return this.http.patch<any>(`${this.base}/customers/${customerId}/name`, { customer_name: name });
  }

  updateTicketCustomName(ticketId: number, name: string | null): Observable<any> {
    return this.http.patch<any>(`${this.base}/tickets/${ticketId}/custom_name`, { customer_name: name });
  }

  setCustomerTags(customerId: number, tagIds: number[]): Observable<any> {
    return this.http.put<any>(`${this.base}/customers/${customerId}/tags`, { tag_ids: tagIds });
  }

  statsQuestions(days: number): Observable<{ ok: boolean; days: number; items: { phrase: string; count: number }[] }> {
    const params = new HttpParams().set('days', String(days)).set('limit', '2000');
    return this.http.get<any>(`${this.base}/stats/questions`, { params });
  }

  // ── 系統 ──────────────────────────────────────────────────

  me() {
    return this.http.get(`${this.base}/staff/me`);
  }

  dashboard() {
    return this.http.get<any>(`${this.base}/dashboard`);
  }

  // ── Ticket 列表 ───────────────────────────────────────────

  listTickets(opts: { status?: string; limit?: number; offset?: number; autofill_subject?: number } = {}) {
    const params = new HttpParams()
      .set('status',           opts.status            ?? 'open,pending')
      .set('limit',            String(opts.limit      ?? 80))
      .set('offset',           String(opts.offset     ?? 0))
      .set('autofill_subject', String(opts.autofill_subject ?? 1));
    return this.http
      .get<any>(`${this.base}/tickets`, { params })
      .pipe(map(res => res?.items ?? res ?? []));
  }

  /** Angular polling 專用：未結案工單 + current_status + is_overdue */
  listActiveTickets(limit = 80, offset = 0): Observable<TicketListItem[]> {
    const params = new HttpParams()
      .set('limit',  String(limit))
      .set('offset', String(offset));
    return this.http
      .get<any>(`${this.base}/tickets/active`, { params })
      .pipe(map(res => res?.items ?? []));
  }

  statusSummary(): Observable<Record<string, number>> {
    return this.http
      .get<any>(`${this.base}/tickets/status_summary`)
      .pipe(map(res => res?.summary ?? {}));
  }

  // ── 訊息 ──────────────────────────────────────────────────

  getMessages(ticketId: number, limit = 200): Observable<TicketMessage[]> {
    const params = new HttpParams().set('limit', String(limit));
    return this.http
      .get<any>(`${this.base}/tickets/${ticketId}/messages`, { params })
      .pipe(map(res => res?.items ?? res ?? []));
  }

  reply(ticketId: number, text: string) {
    return this.http.post(`${this.base}/tickets/${ticketId}/reply`, { text });
  }

  close(ticketId: number) {
    return this.http.post(`${this.base}/tickets/${ticketId}/close`, {});
  }

  // ── 狀態機 ───────────────────────────────────────────────

  getTicketStatus(ticketId: number): Observable<TicketStatusResponse> {
    return this.http.get<any>(`${this.base}/tickets/${ticketId}/status`);
  }

  transition(ticketId: number, status: string, note?: string) {
    return this.http.post(
      `${this.base}/tickets/${ticketId}/transition`,
      { status, note: note ?? null },
    );
  }

  getSessionHistory(ticketId: number): Observable<SessionHistory[]> {
    return this.http
      .get<any>(`${this.base}/tickets/${ticketId}/sessions`)
      .pipe(map(res => res?.items ?? []));
  }

  // ── 報名 ─────────────────────────────────────────────────

  getBooking(ticketId: number): Observable<Booking | null> {
    return this.http
      .get<any>(`${this.base}/tickets/${ticketId}/booking`)
      .pipe(map(res => res?.booking ?? null));
  }

  upsertBooking(ticketId: number, form: Partial<BookingForm>) {
    return this.http.post(`${this.base}/tickets/${ticketId}/booking`, form);
  }

  confirmBooking(ticketId: number, status: 'confirmed' | 'cancelled') {
    return this.http.post(`${this.base}/tickets/${ticketId}/booking/confirm`, { status });
  }

  // ── 客戶筆記 ─────────────────────────────────────────────

  getNotes(ticketId: number): Observable<{ customer_id: number | null; customer_name: string | null; channel_type: string | null; items: CustomerNote[] }> {
    return this.http.get<any>(`${this.base}/tickets/${ticketId}/notes`);
  }

  createNote(ticketId: number, note: string): Observable<any> {
    return this.http.post(`${this.base}/tickets/${ticketId}/notes`, { note });
  }

  updateNote(ticketId: number, noteId: number, note: string): Observable<any> {
    return this.http.put(`${this.base}/tickets/${ticketId}/notes/${noteId}`, { note });
  }

  deleteNote(ticketId: number, noteId: number): Observable<any> {
    return this.http.delete(`${this.base}/tickets/${ticketId}/notes/${noteId}`);
  }

  // ── 媒體 ─────────────────────────────────────────────────

  getContentBlob(lineMessageId: string): Observable<Blob> {
    return this.http.get(`${this.base}/content/${lineMessageId}`, { responseType: 'blob' });
  }

  // ── 繳費訂單 ──────────────────────────────────────────────

  listPaymentOrders(ticketId: number): Observable<any[]> {
    return this.http
      .get<any>(`${this.base}/tickets/${ticketId}/payment`)
      .pipe(map(res => res?.items ?? []));
  }

  createPaymentOrder(ticketId: number, body: { amount: number; description?: string; due_date?: string }): Observable<any> {
    return this.http.post(`${this.base}/tickets/${ticketId}/payment`, body);
  }

  verifyPaymentOrder(orderId: number): Observable<any> {
    return this.http.put(`${this.base}/payment/orders/${orderId}/verify`, {});
  }

  cancelPaymentOrder(orderId: number): Observable<any> {
    return this.http.put(`${this.base}/payment/orders/${orderId}/cancel`, {});
  }

  // ── Quick Reply ───────────────────────────────────────────

  listQuickReplyRules(): Observable<QuickReplyRule[]> {
    return this.http
      .get<any>(`${this.base}/quickreply/rules`)
      .pipe(map(res => res?.items ?? []));
  }

  createQuickReplyRule(body: { keyword: string; reply_text: string; buttons: QuickReplyButton[]; is_active: boolean }): Observable<any> {
    return this.http.post(`${this.base}/quickreply/rules`, body);
  }

  updateQuickReplyRule(ruleId: number, body: Partial<{ keyword: string; reply_text: string; buttons: QuickReplyButton[]; is_active: boolean }>): Observable<any> {
    return this.http.put(`${this.base}/quickreply/rules/${ruleId}`, body);
  }

  deleteQuickReplyRule(ruleId: number): Observable<any> {
    return this.http.delete(`${this.base}/quickreply/rules/${ruleId}`);
  }

  // ── 課程排程 ──────────────────────────────────────────────

  listCourseSchedules(): Observable<CourseSchedule[]> {
    return this.http
      .get<any>(`${this.base}/courses/schedules`)
      .pipe(map(r => r?.items ?? []));
  }

  createCourseSchedule(body: CourseScheduleForm): Observable<any> {
    return this.http.post<any>(`${this.base}/courses/schedules`, body);
  }

  updateCourseSchedule(id: number, body: Partial<CourseScheduleForm>): Observable<any> {
    return this.http.put<any>(`${this.base}/courses/schedules/${id}`, body);
  }

  deleteCourseSchedule(id: number): Observable<any> {
    return this.http.delete<any>(`${this.base}/courses/schedules/${id}`);
  }
}
