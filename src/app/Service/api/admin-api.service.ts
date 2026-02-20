import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { map } from 'rxjs/operators';
import { Observable } from 'rxjs';

import { TicketMessage } from './models';

@Injectable({ providedIn: 'root' })
export class AdminApiService {
  // 走同網域：production 時 environment.apiBase = ''
  // private base = (environment.apiBase || '').replace(/\/$/, '');
  // 因為反向代理，所以用相同網域的 /api 路徑
  private base = '/admin/api';

  constructor(private http: HttpClient) {}

  // 你後端有 /admin/api/dashboard
  dashboard() {
    return this.http.get<any>(`${this.base}/dashboard`);
  }

  // ✅ 驗證 token 是否有效（你 curl 已經打通的那支）
  me() {
  const token = localStorage.getItem('ADMIN_TOKEN') || '';
  const headers = new HttpHeaders({ 'X-Admin-Token': token });
  return this.http.get(`${this.base}/staff/me`, { headers });
    //return this.http.get(`${this.base}/staff/me`);
  }

  // ✅ 票券列表（你後端路徑是 /tickets）
  listTickets(opts: {
    status?: string;   // 'open,pending,closed'
    limit?: number;
    offset?: number;
    autofill_subject?: number; // 1
  } = {}) {
    let params = new HttpParams()
      .set('status', opts.status ?? 'open,pending')
      .set('limit', String(opts.limit ?? 80))
      .set('offset', String(opts.offset ?? 0))
      .set('autofill_subject', String(opts.autofill_subject ?? 1));

    return this.http.get<any>(`${this.base}/tickets`, { params }).pipe(
      map(res => res?.items ?? res ?? [])
    );
  }

  // ✅ messages 正確路徑：/admin/api/tickets/:id/messages
  getMessages(ticketId: number, limit = 200): Observable<TicketMessage[]> {
    const params = new HttpParams().set('limit', String(limit));
    return this.http.get<any>(`${this.base}/tickets/${ticketId}/messages`, { params }).pipe(
      map(res => res?.items ?? res ?? [])
    );
  }

  // ✅ reply 正確路徑：/admin/api/tickets/:id/reply
  reply(ticketId: number, text: string) {
    return this.http.post(`${this.base}/tickets/${ticketId}/reply`, { text });
  }

  // ✅ 結案
  close(ticketId: number) {
    return this.http.post(`${this.base}/tickets/${ticketId}/close`, {});
  }
}
