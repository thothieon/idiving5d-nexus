import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { TicketListItem } from '../../../Service/api/models';

@Component({
  standalone: true,
  selector: 'app-ticket-list-item',
  imports: [CommonModule, RouterLink],
  templateUrl: './ticket-list-item.component.html',
  styleUrl: './ticket-list-item.component.scss',
})
export class TicketListItemComponent {
  @Input({ required: true }) ticket!: TicketListItem;

  fallbackAvatar(name: string | null): string {
    const s = (name ?? '?').trim();
    return s ? s.slice(0, 1).toUpperCase() : '?';
  }

  isOverdue(): boolean {
    const base = this.ticket.updated_at || this.ticket.last_customer_message_at || '';
    const ts = Date.parse(base);
    if (!ts) return false;
    return Date.now() - ts > 60 * 60 * 1000;
  }

  name(): string {
    return this.ticket.customer_name || this.ticket.display_name || '（未知客戶）';
  }

  subject(): string {
    return this.ticket.subject || '（未填 subject）';
  }

  preview(): string {
    return this.ticket.last_in_text || '';
  }
}
