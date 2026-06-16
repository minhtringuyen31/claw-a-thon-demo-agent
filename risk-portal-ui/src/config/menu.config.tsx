import { type MenuConfigType } from '@/components/menu';

const RISK_MENU: MenuConfigType = [
  {
    title: 'Bulletin Board',
    icon: 'notification-on',
    rootPath: '/',
    path: '/bulletin-board'
  },
  {
    title: 'AI Investigation',
    icon: 'category',
    rootPath: '/',
    path: '/ai-investigation'
  },
  {
    title: 'Rule Management',
    icon: 'setting-2',
    rootPath: '/',
    path: '/rule-management'
  },
  {
    title: 'Config Assistant',
    icon: 'messages',
    rootPath: '/',
    path: '/chat-assistant'
  }
];

export const MENU_SIDEBAR: MenuConfigType = RISK_MENU;
export const MENU_MEGA: MenuConfigType = RISK_MENU;
export const MENU_ROOT: MenuConfigType = RISK_MENU;
