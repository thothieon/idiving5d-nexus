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
  StaffItem, StaffPermissions, Tag,
  CourseSchedule, CourseScheduleForm,
  RegCourse, RegCourseForm, RegSession, RegSessionForm, RegRegistration, RegCustomerUpdate,
  CustomerListItem, CustomerDetail, CustomerRegHistory, TodoItem,
  KnowledgeChunk,
} from './models';

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private base = '/admin/api';

  constructor(private http: HttpClient) {}

  // ── 認證 ──────────────────────────────────────────────────

  login(username: string, password: string) {
    return this.http.post<{ ok: boolean; token: string; name: string; role: string; permissions: StaffPermissions | null }>(
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

  staffCreate(body: { name: string; username: string; password: string; role: string; email?: string | null; permissions?: StaffPermissions | null }) {
    return this.http.post<{ ok: boolean; id: number }>(`${this.base}/staff`, body);
  }

  staffUpdate(id: number, body: { name?: string; username?: string; role?: string; is_active?: number; email?: string | null; permissions?: StaffPermissions | null }) {
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

  statsPageViews(days: number, limit = 100): Observable<any> {
    const params = new HttpParams().set('days', String(days)).set('limit', String(limit));
    return this.http.get<any>(`${this.base}/stats/pageviews`, { params });
  }

  statsPageViewsDaily(days: number): Observable<any> {
    const params = new HttpParams().set('days', String(days));
    return this.http.get<any>(`${this.base}/stats/pageviews/daily`, { params });
  }

  statsPageViewsReferrers(days: number): Observable<any> {
    const params = new HttpParams().set('days', String(days));
    return this.http.get<any>(`${this.base}/stats/pageviews/referrers`, { params });
  }

  statsPageViewsDevices(days: number): Observable<any> {
    const params = new HttpParams().set('days', String(days));
    return this.http.get<any>(`${this.base}/stats/pageviews/devices`, { params });
  }

  statsPageViewsSessions(days: number): Observable<any> {
    const params = new HttpParams().set('days', String(days));
    return this.http.get<any>(`${this.base}/stats/pageviews/sessions`, { params });
  }

  statsPageViewsOnline(): Observable<any> {
    return this.http.get<any>(`${this.base}/stats/pageviews/online`);
  }

  statsPageViewsEvents(days: number, eventType = ''): Observable<any> {
    let params = new HttpParams().set('days', String(days)).set('limit', '200');
    if (eventType) params = params.set('event_type', eventType);
    return this.http.get<any>(`${this.base}/stats/pageviews/events`, { params });
  }

  statsPageViewsFunnel(days: number): Observable<any> {
    const params = new HttpParams().set('days', String(days)).set('limit', '100');
    return this.http.get<any>(`${this.base}/stats/pageviews/funnel`, { params });
  }

  // ── 系統 ──────────────────────────────────────────────────

  me() {
    return this.http.get<{ ok: boolean; staff: { role: string; name: string; permissions: StaffPermissions | null } }>(
      `${this.base}/staff/me`
    );
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

  // ── LINE 客服統計 ─────────────────────────────────────────
  lineOverview(days = 7):       Observable<any> { return this.http.get<any>(`${this.base}/stats/line/overview?days=${days}`); }
  lineDaily(days = 30):         Observable<any> { return this.http.get<any>(`${this.base}/stats/line/daily?days=${days}`); }
  linePeakHours(days = 30):     Observable<any> { return this.http.get<any>(`${this.base}/stats/line/peak_hours?days=${days}`); }
  lineTickets(days = 30):       Observable<any> { return this.http.get<any>(`${this.base}/stats/line/tickets?days=${days}`); }
  lineIntents(days = 30):       Observable<any> { return this.http.get<any>(`${this.base}/stats/line/intents?days=${days}`); }
  lineMessageTypes(days = 30):  Observable<any> { return this.http.get<any>(`${this.base}/stats/line/message_types?days=${days}`); }
  lineCourses(days = 30):       Observable<any> { return this.http.get<any>(`${this.base}/stats/line/courses?days=${days}`); }
  lineSendDailyReport():        Observable<any> { return this.http.post<any>(`${this.base}/stats/line/daily_report`, {}); }

  getTicketIntake(ticketId: number): Observable<any> {
    return this.http.get<any>(`${this.base}/tickets/${ticketId}/intake`).pipe(
      map(r => r?.intake ?? null)
    );
  }

  replyImage(ticketId: number, file: File) {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post(`${this.base}/tickets/${ticketId}/reply_image`, form);
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

  getNotes(ticketId: number): Observable<{ customer_id: number | null; customer_name: string | null; channel_type: string | null; channel_id: string | null; items: CustomerNote[] }> {
    return this.http.get<any>(`${this.base}/tickets/${ticketId}/notes`);
  }

  getChannelTags(channelType: string, channelId: string): Observable<Tag[]> {
    return this.http.get<any>(`${this.base}/channels/${channelType}/${channelId}/tags`).pipe(map(r => r.items ?? []));
  }

  setChannelTags(channelType: string, channelId: string, tagIds: number[]): Observable<any> {
    return this.http.put<any>(`${this.base}/channels/${channelType}/${channelId}/tags`, { tag_ids: tagIds });
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

  // ── 報名系統 ──────────────────────────────────────────────

  regListCourses(): Observable<RegCourse[]> {
    return this.http.get<RegCourse[]>(`${this.base}/reg/courses`);
  }

  regCreateCourse(body: RegCourseForm): Observable<{ id: number }> {
    return this.http.post<{ id: number }>(`${this.base}/reg/courses`, body);
  }

  regUpdateCourse(id: number, body: Partial<RegCourseForm>): Observable<any> {
    return this.http.put<any>(`${this.base}/reg/courses/${id}`, body);
  }

  regListSessions(courseId?: number): Observable<RegSession[]> {
    const url = courseId
      ? `${this.base}/reg/sessions?course_id=${courseId}`
      : `${this.base}/reg/sessions`;
    return this.http.get<RegSession[]>(url);
  }

  regCreateSession(body: RegSessionForm): Observable<{ id: number }> {
    return this.http.post<{ id: number }>(`${this.base}/reg/sessions`, body);
  }

  regUpdateSession(id: number, body: Partial<RegSessionForm>): Observable<any> {
    return this.http.put<any>(`${this.base}/reg/sessions/${id}`, body);
  }

  regListRegistrations(params: {
    session_id?: number;
    course_id?: number;
    reg_status?: string;
  }): Observable<RegRegistration[]> {
    let p = new HttpParams();
    if (params.session_id) p = p.set('session_id', params.session_id);
    if (params.course_id)  p = p.set('course_id',  params.course_id);
    if (params.reg_status) p = p.set('reg_status',  params.reg_status);
    return this.http.get<RegRegistration[]>(`${this.base}/reg/registrations`, { params: p });
  }

  regUpdateRegistration(id: number, body: {
    reg_status?: string;
    payment_status?: string;
    notes?: string;
  }): Observable<any> {
    return this.http.put<any>(`${this.base}/reg/registrations/${id}`, body);
  }

  regUpdateCustomer(customerId: number, body: RegCustomerUpdate): Observable<any> {
    return this.http.put<any>(`${this.base}/reg/customers/${customerId}`, body);
  }

  regConfirmData(regId: number): Observable<any> {
    return this.http.post<any>(`${this.base}/reg/registrations/${regId}/confirm-data`, {});
  }

  regConfirmPayment(regId: number): Observable<any> {
    return this.http.post<any>(`${this.base}/reg/registrations/${regId}/confirm-payment`, {});
  }

  regResendEmail(regId: number): Observable<any> {
    return this.http.post<any>(`${this.base}/reg/registrations/${regId}/resend-email`, {});
  }

  // ── 客戶管理 ────────────────────────────────────────────────

  customerList(q: string, offset: number, limit: number): Observable<{ total: number; items: CustomerListItem[] }> {
    let params = new HttpParams().set('limit', limit).set('offset', offset);
    if (q) params = params.set('q', q);
    return this.http.get<{ total: number; items: CustomerListItem[] }>(`${this.base}/reg/customers`, { params });
  }

  customerGet(id: number): Observable<{ customer: CustomerDetail; registrations: CustomerRegHistory[] }> {
    return this.http.get<{ customer: CustomerDetail; registrations: CustomerRegHistory[] }>(`${this.base}/reg/customers/${id}`);
  }

  customerUpdate(id: number, body: RegCustomerUpdate): Observable<any> {
    return this.http.put<any>(`${this.base}/reg/customers/${id}`, body);
  }

  // ── 待處理清單 ────────────────────────────────────────────

  todoList(showDone = 0, ticketId?: number): Observable<{ items: TodoItem[] }> {
    const p: any = { show_done: showDone };
    if (ticketId != null) p.ticket_id = ticketId;
    return this.http.get<{ items: TodoItem[] }>(`${this.base}/todos`, { params: p });
  }

  todoCreate(body: { title: string; note?: string; assignee_id?: number | null; due_date?: string | null; ticket_id?: number | null; priority?: number }): Observable<{ ok: boolean; id: number }> {
    return this.http.post<{ ok: boolean; id: number }>(`${this.base}/todos`, body);
  }

  todoPatch(id: number, body: Partial<{ title: string; note: string; assignee_id: number | null; due_date: string | null; ticket_id: number | null; priority: number; is_done: number }>): Observable<any> {
    return this.http.patch<any>(`${this.base}/todos/${id}`, body);
  }

  todoDelete(id: number): Observable<any> {
    return this.http.delete<any>(`${this.base}/todos/${id}`);
  }

  // ── RAG 知識庫 ────────────────────────────────────────────────

  ragList(category?: string): Observable<{ items: KnowledgeChunk[] }> {
    const params: Record<string, string> = {};
    if (category) params['category'] = category;
    return this.http.get<{ items: KnowledgeChunk[] }>(`${this.base}/rag/chunks`, { params });
  }

  ragCreate(body: { category: string; title: string; content: string; is_active?: number }): Observable<{ ok: boolean; id: number; embedded: boolean }> {
    return this.http.post<{ ok: boolean; id: number; embedded: boolean }>(`${this.base}/rag/chunks`, body);
  }

  ragUpdate(id: number, body: Partial<{ category: string; title: string; content: string; is_active: number }>): Observable<{ ok: boolean }> {
    return this.http.patch<{ ok: boolean }>(`${this.base}/rag/chunks/${id}`, body);
  }

  ragDelete(id: number): Observable<{ ok: boolean }> {
    return this.http.delete<{ ok: boolean }>(`${this.base}/rag/chunks/${id}`);
  }

  ragReembedAll(): Observable<{ ok: boolean; updated: number }> {
    return this.http.post<{ ok: boolean; updated: number }>(`${this.base}/rag/chunks/reembed-all`, {});
  }

  regExportUrl(params: { session_id?: number; course_id?: number; reg_status?: string }): string {
    const q = new URLSearchParams();
    if (params.session_id) q.set('session_id', String(params.session_id));
    if (params.course_id)  q.set('course_id',  String(params.course_id));
    if (params.reg_status) q.set('reg_status',  params.reg_status);
    const token = localStorage.getItem('ADMIN_TOKEN') ?? '';
    q.set('x_admin_token', token);
    return `${this.base}/reg/registrations/export?${q.toString()}`;
  }
}
