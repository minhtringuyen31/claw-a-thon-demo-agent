import { ReactElement, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router';
import { DemoPage } from '@/pages/demo/DemoPage';
import { InvestigationListPage } from '@/pages/ai-investigation/InvestigationListPage';
import { InvestigationDetailPage } from '@/pages/ai-investigation/InvestigationDetailPage';
import { AiAssistantPage } from '@/pages/ai-assistant/AiAssistantPage';
import { RuleManagementPage } from '@/pages/rule-management/RuleManagementPage';
import { ChatAssistantPage } from '@/pages/chat-assistant/ChatAssistantPage';

import { Demo1Layout } from '../layouts/demo1';
import { ErrorsRouting } from '../errors';
import { useLoaders } from '../providers/LoadersProvider';

const AppRouting = (): ReactElement => {
  const { setProgressBarLoader } = useLoaders();
  const [previousLocation, setPreviousLocation] = useState('');
  const location = useLocation();
  const path = location.pathname.trim();

  useEffect(() => {
    setProgressBarLoader(true);
    setPreviousLocation(path);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location]);

  useEffect(() => {
    setProgressBarLoader(false);
    if (!CSS.escape(window.location.hash)) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previousLocation]);

  return (
    <Routes>
      <Route element={<Demo1Layout />}>
        <Route path="/" element={<Navigate to="/bulletin-board" replace />} />
        <Route path="bulletin-board" element={<DemoPage title="Demo Page" />} />
        <Route path="ai-investigation" element={<InvestigationListPage />} />
        <Route path="ai-investigation/:id" element={<InvestigationDetailPage />} />
        <Route path="ai-investigation/:runId/assistant" element={<AiAssistantPage />} />
        <Route path="rule-management" element={<RuleManagementPage />} />
        <Route path="chat-assistant" element={<ChatAssistantPage />} />
      </Route>
      <Route path="error/*" element={<ErrorsRouting />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export { AppRouting };
