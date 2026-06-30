import React, {lazy, Suspense, useEffect, useState} from 'react';
import 'material-react-toastify/dist/ReactToastify.css';
import './lib/variables.scss'
import './lib/global.scss'
import './lib/layout.scss'

import {BrowserRouter as Router, Route, Routes} from "react-router";
import PubSub from 'pubsub-js';
import events from './lib/events';
import {LocalizationProvider} from '@mui/x-date-pickers/LocalizationProvider';
import {AdapterDayjs} from '@mui/x-date-pickers/AdapterDayjs';
import {KeyStatesProvider} from './services/keys/keyStates';
import {ToastContainer} from "material-react-toastify";
import {incorporateArrayInQueue, IPopupAlert, IPreparedPopupAlert} from "./services/alerts/alerts";
import AlertQueueModal from "./services/alerts/AlertQueueModal";

// Login is the landing route — keep it eager so first paint isn't gated on a
// second network round-trip. SharePasswordGate wraps most routes and is tiny.
import Login from "./pages/Login";
import SharePasswordGate from "./UIComponents/LinkSharing/SharePasswordGate";

// Everything below is code-split: each page (and the heavy libs it pulls in —
// x-data-grid, query-builder, react-json-view, zxcvbn) loads on navigation
// rather than being baked into the initial bundle.
const NoMatch = lazy(() => import("./pages/404"));
const AccountPage = lazy(() => import("./pages/AccountPage"));
const PostPage = lazy(() => import("./pages/PostPage"));
const MediaPage = lazy(() => import("./pages/MediaPage"));
const SessionPage = lazy(() => import("./pages/SessionPage"));
const SearchPage = lazy(() => import("./pages/SearchPage"));
const UploadPage = lazy(() => import("./pages/Upload"));
const IncorporatePage = lazy(() => import("./pages/Incorporate"));
const TagManagementPage = lazy(() => import("./pages/TagManagementPage"));
const EditTagPage = lazy(() => import("./pages/EditTagPage"));
const SecuritySettings = lazy(() => import("./pages/SecuritySettings"));
const AdminUsersPage = lazy(() => import("./pages/AdminUsersPage"));
const CommunityDetectionPage = lazy(() => import("./pages/CommunityDetectionPage"));

export default function App() {
    const [alertQueue, setAlertQueue] = useState<IPreparedPopupAlert[]>([]);

    useEffect(() => {
        // Clean up stale TUS upload fingerprints that accumulate in localStorage
        Object.keys(localStorage).filter(k => k.startsWith('tus::')).forEach(k => localStorage.removeItem(k));

        function hideError(e: ErrorEvent) {
            if (e.message === 'ResizeObserver loop completed with undelivered notifications.') {
                const resizeObserverErrDiv = document.getElementById('webpack-dev-server-client-overlay-div');
                const resizeObserverErr = document.getElementById('webpack-dev-server-client-overlay');
                if (resizeObserverErr) resizeObserverErr.setAttribute('style', 'display: none');
                if (resizeObserverErrDiv) resizeObserverErrDiv.setAttribute('style', 'display: none');
            }
        }
        window.addEventListener('error', hideError);

        const alertToken = PubSub.subscribe(events.alert, (_: string, alert: IPopupAlert) => {
            setAlertQueue(curr => incorporateArrayInQueue(curr.slice(), alert));
        });
        const clearToken = PubSub.subscribe(events.clearAlert, (_: string, alertId: number) => {
            setAlertQueue(curr => curr.filter(a => a.id !== alertId));
        });

        return () => {
            window.removeEventListener('error', hideError);
            PubSub.unsubscribe(alertToken);
            PubSub.unsubscribe(clearToken);
        };
    }, []);

    return (
        <LocalizationProvider dateAdapter={AdapterDayjs}>
        <KeyStatesProvider>
            <Router>
                <meta/>
                <Suspense fallback={<div style={{padding: 24}}>Loading…</div>}>
                <Routes>
                    <Route path="/" element={<Login/>}/>
                    <Route path="/login" element={<Login/>}/>
                    <Route path="/account/pk/:platformId" element={<SharePasswordGate><AccountPage/></SharePasswordGate>}/>
                    <Route path="/account/url/*" element={<SharePasswordGate><AccountPage/></SharePasswordGate>}/>
                    <Route path="/account/:id" element={<SharePasswordGate><AccountPage/></SharePasswordGate>}/>
                    <Route path="/post/pk/:platformId" element={<SharePasswordGate><PostPage/></SharePasswordGate>}/>
                    <Route path="/post/url/*" element={<SharePasswordGate><PostPage/></SharePasswordGate>}/>
                    <Route path="/post/:id" element={<SharePasswordGate><PostPage/></SharePasswordGate>}/>
                    <Route path="/media/pk/:platformId" element={<SharePasswordGate><MediaPage/></SharePasswordGate>}/>
                    <Route path="/media/:id" element={<SharePasswordGate><MediaPage/></SharePasswordGate>}/>
                    <Route path="/archive/:id" element={<SharePasswordGate><SessionPage/></SharePasswordGate>}/>
                    <Route path="/search" element={<SearchPage/>}/>
                    <Route path="/community" element={<CommunityDetectionPage/>}/>
                    <Route path="/upload" element={<UploadPage/>}/>
                    <Route path="/incorporate" element={<IncorporatePage/>}/>
                    <Route path="/tags" element={<TagManagementPage/>}/>
                    <Route path="/tags/:tag_id" element={<EditTagPage/>}/>
                    <Route path="/settings/security" element={<SecuritySettings/>}/>
                    <Route path="/admin/users" element={<AdminUsersPage/>}/>
                    <Route path="/*" element={<NoMatch/>}/>
                </Routes>
                </Suspense>
                <ToastContainer
                    position="bottom-left"
                    bodyStyle={{color: '#000'}}
                />
                <AlertQueueModal alertQueue={alertQueue}/>
            </Router>
        </KeyStatesProvider>
        </LocalizationProvider>
    );
}
