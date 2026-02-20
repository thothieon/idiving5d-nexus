import { Injectable, signal } from '@angular/core';

const KEY = 'ADMIN_TOKEN';

@Injectable({ providedIn: 'root' })
export class AdminTokenService {
  private _token = signal<string>(localStorage.getItem(KEY) ?? '');
  private readonly TOKEN_KEY = 'ADMIN_TOKEN';

  /** 取得存儲的 token */
  get(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  token() { return this._token(); }
  has() { return !!this._token(); }

  set(token: string) {
    const t = (token ?? '').trim();
    localStorage.setItem(KEY, t);
    this._token.set(t);
  }

  clear() {
    localStorage.removeItem(KEY);
    this._token.set('');
  }
}
