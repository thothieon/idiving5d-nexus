import { Injectable, signal } from '@angular/core';

const KEY_TOKEN = 'ADMIN_TOKEN';
const KEY_ROLE  = 'ADMIN_ROLE';
const KEY_NAME  = 'ADMIN_NAME';

@Injectable({ providedIn: 'root' })
export class AdminTokenService {
  private _token = signal<string>(localStorage.getItem(KEY_TOKEN) ?? '');
  private _role  = signal<string>(localStorage.getItem(KEY_ROLE)  ?? '');
  private _name  = signal<string>(localStorage.getItem(KEY_NAME)  ?? '');

  /** 取得存儲的 token */
  get(): string | null {
    return localStorage.getItem(KEY_TOKEN);
  }

  token()   { return this._token(); }
  role()    { return this._role(); }
  name()    { return this._name(); }
  has()     { return !!this._token(); }
  isAdmin() { return this._role() === 'admin'; }

  set(token: string, role = '', name = '') {
    const t = (token ?? '').trim();
    localStorage.setItem(KEY_TOKEN, t);
    localStorage.setItem(KEY_ROLE,  role);
    localStorage.setItem(KEY_NAME,  name);
    this._token.set(t);
    this._role.set(role);
    this._name.set(name);
  }

  clear() {
    localStorage.removeItem(KEY_TOKEN);
    localStorage.removeItem(KEY_ROLE);
    localStorage.removeItem(KEY_NAME);
    this._token.set('');
    this._role.set('');
    this._name.set('');
  }
}
