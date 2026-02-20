import { Injectable } from '@angular/core';

const KEY = 'admin_token';

@Injectable({ providedIn: 'root' })
export class TokenService {
  get(): string | null {
    return localStorage.getItem(KEY);
  }
  set(token: string) {
    localStorage.setItem(KEY, token.trim());
  }
  clear() {
    localStorage.removeItem(KEY);
  }
  has(): boolean {
    return !!this.get();
  }
}
