// admin-api.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { map } from 'rxjs/operators';
import { Observable } from 'rxjs';

import {
  TicketMessage, TicketListItem,
  TicketStatusResponse, SessionHistory,
  Booking, BookingForm, CustomerNote,
} from './models';

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  private base = '/admin/api';

  constructor(private http: HttpClient) {}

  private authHeaders(): HttpHeaders {
    const token = localStorage.getItem('ADMIN_TOKEN') || '';
    return new HttpHeaders({ 'X-Admin-Token': token });
  }

  // ── 系統 ──────────────────────────────────────────────────

  me() {
    return this.http.get(`${this.base}/staff/me`, { headers: this.authHeaders() });
  }

  dashboard() {
    return this.http.get<any>(`${this.base}/dashboard`, { headers: this.authHeaders() });
  }

  // ── Ticket 列表 ───────────────────────────────────────────

  listTickets(opts: { status?: string; limit?: number; offset?: number; autofill_subject?: number } = {}) {
    const params = new HttpParams()
      .set('status',           opts.status            ?? 'open,pending')
      .set('limit',            String(opts.limit      ?? 80))
      .set('offset',           String(opts.offset     ?? 0))
      .set('autofill_subject', String(opts.autofill_subject ?? 1));
    return this.http
      .get<any>(`${this.base}/tickets`, { headers: this.authHeaders(), params })
      .pipe(map(res => res?.items ?? res ?? []));
  }

  /** Angular polling 專用：未結案工單 + current_status + is_overdue */
  listActiveTickets(limit = 80, offset = 0): Observable<TicketListItem[]> {
    const params = new HttpParams()
      .set('limit',  String(limit))
      .set('offset', String(offset));
    return this.http
      .get<any>(`${this.base}/tickets/active`, { headers: this.authHeaders(), params })
      .pipe(map(res => res?.items ?? []));
  }

  statusSummary(): Observable<Record<string, number>> {
    return this.http
      .get<any>(`${this.base}/tickets/status_summary`, { headers: this.authHeaders() })
      .pipe(map(res => res?.summary ?? {}));
  }

  // ── 訊息 ──────────────────────────────────────────────────

  getMessages(ticketId: number, limit = 200): Observable<TicketMessage[]> {
    const params = new HttpParams().set('limit', String(limit));
    return this.http
      .get<any>(`${this.base}/tickets/${ticketId}/messages`, { headers: this.authHeaders(), params })
      .pipe(map(res => res?.items ?? res ?? []));
  }

  reply(ticketId: number, text: string) {
    return this.http.post(
      `${this.base}/tickets/${ticketId}/reply`,
      { text },
      { headers: this.authHeaders() },
    );
  }

  close(ticketId: number) {
    return this.http.post(
      `${this.base}/tickets/${ticketId}/close`,
      {},
      { headers: this.authHeaders() },
    );
  }

  // ── 狀態機 ───────────────────────────────────────────────

  getTicketStatus(ticketId: number): Observable<TicketStatusResponse> {
    return this.http.get<any>(
      `${this.base}/tickets/${ticketId}/status`,
      { headers: this.authHeaders() },
    );
  }

  transition(ticketId: number, status: string, note?: string) {
    return this.http.post(
      `${this.base}/tickets/${ticketId}/transition`,
      { status, note: note ?? null },
      { headers: this.authHeaders() },
    );
  }

  getSessionHistory(ticketId: number): Observable<SessionHistory[]> {
    return this.http
      .get<any>(`${this.base}/tickets/${ticketId}/sessions`, { headers: this.authHeaders() })
      .pipe(map(res => res?.items ?? []));
  }

  // ── 報名 ─────────────────────────────────────────────────

  getBooking(ticketId: number): Observable<Booking | null> {
    return this.http
      .get<any>(`${this.base}/tickets/${ticketId}/booking`, { headers: this.authHeaders() })
      .pipe(map(res => res?.booking ?? null));
  }

  upsertBooking(ticketId: number, form: Partial<BookingForm>) {
    return this.http.post(
      `${this.base}/tickets/${ticketId}/booking`,
      form,
      { headers: this.authHeaders() },
    );
  }

  confirmBooking(ticketId: number, status: 'confirmed' | 'cancelled') {
    return this.http.post(
      `${this.base}/tickets/${ticketId}/booking/confirm`,
      { status },
      { headers: this.authHeaders() },
    );
  }

  // ── 客戶筆記 ─────────────────────────────────────────────

  getNotes(ticketId: number): Observable<{ customer_id: number | null; items: CustomerNote[] }> {
    return this.http.get<any>(
      `${this.base}/tickets/${ticketId}/notes`,
      { headers: this.authHeaders() },
    );
  }

  createNote(ticketId: number, note: string): Observable<any> {
    return this.http.post(
      `${this.base}/tickets/${ticketId}/notes`,
      { note },
      { headers: this.authHeaders() },
    );
  }

  updateNote(ticketId: number, noteId: number, note: string): Observable<any> {
    return this.http.put(
      `${this.base}/tickets/${ticketId}/notes/${noteId}`,
      { note },
      { headers: this.authHeaders() },
    );
  }

  deleteNote(ticketId: number, noteId: number): Observable<any> {
    return this.http.delete(
      `${this.base}/tickets/${ticketId}/notes/${noteId}`,
      { headers: this.authHeaders() },
    );
  }

  // ── 媒體 ─────────────────────────────────────────────────

  getContentBlob(lineMessageId: string): Observable<Blob> {
    return this.http.get(`${this.base}/content/${lineMessageId}`, {
      headers: this.authHeaders(),
      responseType: 'blob',
    });
  }
}
