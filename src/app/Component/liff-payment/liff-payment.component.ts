import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';

import { LiffPendingOrder, LiffSubmitResult } from '../../Service/api/models';

declare const liff: any;

const LIFF_ID   = '2009420432-ZWrRUmas';
const LIFF_BASE = '/liff';

type Phase = 'init' | 'loading' | 'select' | 'form' | 'submitting' | 'success' | 'error' | 'empty';

@Component({
  standalone: true,
  selector: 'app-liff-payment',
  imports: [CommonModule, FormsModule],
  templateUrl: './liff-payment.component.html',
  styleUrl: './liff-payment.component.scss',
})
export class LiffPaymentComponent implements OnInit {
  phase: Phase = 'init';
  errorMsg = '';

  orders: LiffPendingOrder[] = [];
  selected: LiffPendingOrder | null = null;

  last5  = '';
  amount = 0;

  resultMsg = '';

  private idToken = '';

  constructor(private http: HttpClient) {}

  ngOnInit() {
    // 15 秒 timeout，幫助診斷卡在哪個階段
    const initTimer = setTimeout(() => {
      if (this.phase === 'init') {
        this.errorMsg = 'LIFF 初始化逾時（15s），請確認 LIFF Endpoint URL 設定是否正確';
        this.phase = 'error';
      }
    }, 15000);

    const loadTimer = setTimeout(() => {
      if (this.phase === 'loading') {
        this.errorMsg = 'API 呼叫逾時（20s），請稍後再試';
        this.phase = 'error';
      }
    }, 20000);

    liff.init({ liffId: LIFF_ID })
      .then(() => {
        clearTimeout(initTimer);
        if (!liff.isLoggedIn()) {
          clearTimeout(loadTimer);
          liff.login();
          return;
        }
        this.idToken = liff.getIDToken() ?? '';
        this.loadOrders();
      })
      .catch((err: any) => {
        clearTimeout(initTimer);
        clearTimeout(loadTimer);
        this.errorMsg = `LIFF 初始化失敗：${err?.message ?? err}`;
        this.phase = 'error';
      });
  }

  private loadOrders() {
    this.phase = 'loading';
    this.http.post<{ ok: boolean; items: LiffPendingOrder[] }>(
      `${LIFF_BASE}/payment/orders`,
      { id_token: this.idToken },
    ).subscribe({
      next: (res) => {
        this.orders = res.items ?? [];
        if (this.orders.length === 0) {
          this.phase = 'empty';
        } else if (this.orders.length === 1) {
          this.selectOrder(this.orders[0]);
        } else {
          this.phase = 'select';
        }
      },
      error: (e) => {
        this.errorMsg = e?.error?.detail ?? '無法取得訂單資料，請稍後再試';
        this.phase = 'error';
      },
    });
  }

  selectOrder(order: LiffPendingOrder) {
    this.selected = order;
    this.amount   = order.amount;
    this.last5    = '';
    this.phase    = 'form';
  }

  backToSelect() {
    this.selected = null;
    this.phase    = 'select';
  }

  submit() {
    const last5 = (this.last5 || '').trim();
    if (!/^\d{5}$/.test(last5)) {
      this.errorMsg = '請輸入正確的 5 位數末五碼';
      return;
    }
    if (!this.amount || this.amount <= 0) {
      this.errorMsg = '請輸入正確的金額';
      return;
    }
    if (!this.selected) return;

    this.errorMsg = '';
    this.phase = 'submitting';

    this.http.post<LiffSubmitResult>(
      `${LIFF_BASE}/payment/submit`,
      {
        id_token: this.idToken,
        order_id: this.selected.id,
        last5,
        amount: this.amount,
      },
    ).subscribe({
      next: (res) => {
        this.resultMsg = res.message;
        this.phase = 'success';
      },
      error: (e) => {
        this.errorMsg = e?.error?.detail ?? '提交失敗，請稍後再試';
        this.phase = 'form';
      },
    });
  }

  closeLiff() {
    liff.closeWindow();
  }
}
