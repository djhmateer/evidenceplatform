import React, {useEffect, useState} from 'react';
import {toast} from "material-react-toastify";
import TextField from '@mui/material/TextField';
import {
    Button,
    CircularProgress,
    Divider,
    Fab,
    FormControlLabel,
    IconButton,
    Stack,
    Switch,
    Tooltip,
    Typography,
} from "@mui/material";
import {ContentCopy, Lock, LockOpen, Share, Visibility, VisibilityOff} from "@mui/icons-material";
import server from "../../services/server";
import InputAdornment from "@mui/material/InputAdornment";
import {NoMaxWidthTooltip} from "../StyledComponents/CustomTooltips";
import {SHARE_URL_PARAM} from "../../services/linkSharing";
import {E_ENTITY_TYPES} from "../../types/entities";


interface IProps {
    entityType: E_ENTITY_TYPES,
    entityId: number,
    stableSharePath?: string,
}

interface ShareLinkInfo {
    suffix: string;
    valid: boolean;
    include_screen_recordings: boolean;
    include_har: boolean;
    password_protected: boolean;
}

export default function LinkSharing({entityType, entityId, stableSharePath}: IProps) {
    const [isFetching, setIsFetching] = useState(false);
    const [isTogglingValidity, setIsTogglingValidity] = useState(false);
    const [isUpdatingAccess, setIsUpdatingAccess] = useState(false);
    const [isUpdatingPassword, setIsUpdatingPassword] = useState(false);
    const [shareLinkInfo, setShareLinkInfo] = useState<ShareLinkInfo | null>(null);
    const [generationError, setGenerationError] = useState<string | null>(null);
    const [pendingIncludeRecordings, setPendingIncludeRecordings] = useState(false);
    const [pendingIncludeHar, setPendingIncludeHar] = useState(false);
    const [passwordEnabled, setPasswordEnabled] = useState(false);
    const [pendingPassword, setPendingPassword] = useState('');
    const [showPendingPassword, setShowPendingPassword] = useState(false);
    const [passwordError, setPasswordError] = useState<string | null>(null);

    const shareLinkFromSuffix = (suffix: string) => {
        const base = stableSharePath
            ? new URL(stableSharePath, window.location.origin)
            : new URL(window.location.href);
        base.searchParams.set(SHARE_URL_PARAM, suffix);
        return base.toString();
    };

    useEffect(() => {
        setShareLinkInfo(null);
        setGenerationError(null);
        setIsFetching(true);
        server.get(`share/${entityType}/${entityId}/`).then((response: {
            link_suffix: string,
            valid: boolean,
            include_screen_recordings: boolean,
            include_har: boolean,
            password_protected: boolean,
        } | null) => {
            if (response) {
                const info: ShareLinkInfo = {
                    suffix: response.link_suffix,
                    valid: response.valid,
                    include_screen_recordings: response.include_screen_recordings,
                    include_har: response.include_har,
                    password_protected: response.password_protected,
                };
                setShareLinkInfo(info);
                setPendingIncludeRecordings(info.include_screen_recordings);
                setPendingIncludeHar(info.include_har);
                setPasswordEnabled(info.password_protected);
            }
            setIsFetching(false);
        });
    }, [entityType, entityId]);

    const generateShareLink = async () => {
        setIsFetching(true);
        const response: {
            success: boolean, link_suffix: null | string, error: null | string
        } = await server.post(`share/`, {
            view: true,
            shared_entity: {entity: entityType, entity_id: entityId},
            include_screen_recordings: pendingIncludeRecordings,
            include_har: pendingIncludeHar,
        });
        if (response.success && response.link_suffix) {
            setShareLinkInfo({
                suffix: response.link_suffix,
                valid: true,
                include_screen_recordings: pendingIncludeRecordings,
                include_har: pendingIncludeHar,
                password_protected: false,
            });
            setGenerationError(null);
        } else {
            setGenerationError(response.error || "Unknown error");
        }
        setIsFetching(false);
    };

    const copyShareLinkToClipboard = () => {
        if (shareLinkInfo) {
            navigator.clipboard.writeText(shareLinkFromSuffix(shareLinkInfo.suffix));
            toast.success("Link copied to clipboard!");
        }
    };

    const handleToggleValidity = async () => {
        if (!shareLinkInfo) return;
        const newValid = !shareLinkInfo.valid;
        setIsTogglingValidity(true);
        await server.post(`share/${entityType}/${entityId}/valid`, {valid: newValid});
        setShareLinkInfo({...shareLinkInfo, valid: newValid});
        setIsTogglingValidity(false);
    };

    const handleAttachmentAccessChange = async (
        includeRecordings: boolean,
        includeHar: boolean,
    ) => {
        if (!shareLinkInfo) return;
        setIsUpdatingAccess(true);
        await server.post(`share/${entityType}/${entityId}/attachment_access`, {
            include_screen_recordings: includeRecordings,
            include_har: includeHar,
        });
        setShareLinkInfo({...shareLinkInfo, include_screen_recordings: includeRecordings, include_har: includeHar});
        setIsUpdatingAccess(false);
    };

    const handlePasswordToggle = async (enabled: boolean) => {
        if (!shareLinkInfo) return;
        setPasswordEnabled(enabled);
        setPasswordError(null);
        setPendingPassword('');
        if (!enabled) {
            setIsUpdatingPassword(true);
            try {
                await server.post(`share/${entityType}/${entityId}/password`, {password: null});
                setShareLinkInfo({...shareLinkInfo, password_protected: false});
            } catch {
                setPasswordEnabled(true);
            }
            setIsUpdatingPassword(false);
        }
    };

    const handlePasswordSave = async () => {
        if (!shareLinkInfo) return;
        if (pendingPassword.length < 6) {
            setPasswordError('Password must be at least 6 characters');
            return;
        }
        setIsUpdatingPassword(true);
        setPasswordError(null);
        try {
            await server.post(`share/${entityType}/${entityId}/password`, {password: pendingPassword});
            setShareLinkInfo({...shareLinkInfo, password_protected: true});
            setPendingPassword('');
            toast.success('Password saved');
        } catch (e: any) {
            setPasswordError(e?.message || 'Failed to save password');
        }
        setIsUpdatingPassword(false);
    };

    const attachmentAccessControls = (
        includeRecordings: boolean,
        includeHar: boolean,
        onChangeRecordings: (v: boolean) => void,
        onChangeHar: (v: boolean) => void,
        disabled?: boolean,
    ) => (
        <Stack spacing={0.5}>
            <Typography variant="caption" color="text.secondary">Attachment access</Typography>
            <FormControlLabel
                control={
                    <Switch checked={includeRecordings} onChange={e => onChangeRecordings(e.target.checked)}
                            size="small" disabled={disabled}/>
                }
                label={<Typography variant="body2">Screen recordings</Typography>}
            />
            <FormControlLabel
                control={
                    <Switch checked={includeHar} onChange={e => onChangeHar(e.target.checked)}
                            size="small" disabled={disabled}/>
                }
                label={<Typography variant="body2">HAR files</Typography>}
            />
        </Stack>
    );

    const fabColor = shareLinkInfo
        ? (shareLinkInfo.valid ? "success" : "warning")
        : "primary";

    const tooltipContent = isFetching
        ? <CircularProgress size={20} color="primary"/>
        : shareLinkInfo
            ? <Stack spacing={1}>
                <TextField
                    value={shareLinkFromSuffix(shareLinkInfo.suffix)}
                    size="small"
                    variant="outlined"
                    disabled={!shareLinkInfo.valid}
                    inputProps={{readOnly: true}}
                    InputProps={{
                        endAdornment: (
                            <InputAdornment position="end">
                                <Tooltip title="Copy">
                                    <IconButton size="small" onClick={copyShareLinkToClipboard}
                                                disabled={!shareLinkInfo.valid}>
                                        <ContentCopy fontSize="small"/>
                                    </IconButton>
                                </Tooltip>
                            </InputAdornment>
                        )
                    }}
                    sx={{
                        padding: 0,
                        background: "white",
                        borderRadius: "inherit",
                        width: `${Math.max(10, shareLinkFromSuffix(shareLinkInfo.suffix).length)}ch`,
                    }}
                />
                {isTogglingValidity
                    ? <CircularProgress size={20} color="primary"/>
                    : <FormControlLabel
                        control={
                            <Switch
                                checked={shareLinkInfo.valid}
                                onChange={handleToggleValidity}
                                size="small"
                                color="success"
                            />
                        }
                        label={
                            <Typography variant="body2" color="text.secondary">
                                {shareLinkInfo.valid ? "Active" : "Disabled"}
                            </Typography>
                        }
                    />
                }
                <Divider/>
                {isUpdatingAccess
                    ? <CircularProgress size={20} color="primary"/>
                    : attachmentAccessControls(
                        shareLinkInfo.include_screen_recordings,
                        shareLinkInfo.include_har,
                        (v) => handleAttachmentAccessChange(v, shareLinkInfo.include_har),
                        (v) => handleAttachmentAccessChange(shareLinkInfo.include_screen_recordings, v),
                    )
                }
                <Divider/>
                <Stack spacing={0.5}>
                    <Typography variant="caption" color="text.secondary">Password protection</Typography>
                    {isUpdatingPassword
                        ? <CircularProgress size={20} color="primary"/>
                        : <FormControlLabel
                            control={
                                <Switch
                                    checked={passwordEnabled}
                                    onChange={e => handlePasswordToggle(e.target.checked)}
                                    size="small"
                                    color="warning"
                                />
                            }
                            label={
                                <Stack direction="row" alignItems="center" gap={0.5}>
                                    {shareLinkInfo.password_protected
                                        ? <Lock fontSize="small" color="warning"/>
                                        : <LockOpen fontSize="small" color="disabled"/>
                                    }
                                    <Typography variant="body2">
                                        {shareLinkInfo.password_protected ? 'Protected' : 'No password'}
                                    </Typography>
                                </Stack>
                            }
                        />
                    }
                    {passwordEnabled && (
                        <Stack spacing={1}>
                            <TextField
                                size="small"
                                label={shareLinkInfo.password_protected ? 'New password' : 'Set password'}
                                type={showPendingPassword ? 'text' : 'password'}
                                value={pendingPassword}
                                onChange={e => {setPendingPassword(e.target.value); setPasswordError(null);}}
                                error={!!passwordError}
                                helperText={passwordError}
                                inputProps={{autoComplete: 'new-password'}}
                                InputProps={{
                                    endAdornment: (
                                        <InputAdornment position="end">
                                            <IconButton size="small" onClick={() => setShowPendingPassword(v => !v)}>
                                                {showPendingPassword ? <VisibilityOff fontSize="small"/> : <Visibility fontSize="small"/>}
                                            </IconButton>
                                        </InputAdornment>
                                    ),
                                }}
                            />
                            <Button
                                size="small"
                                variant="contained"
                                color="warning"
                                onClick={handlePasswordSave}
                                disabled={isUpdatingPassword || !pendingPassword}
                            >
                                Save password
                            </Button>
                        </Stack>
                    )}
                </Stack>
            </Stack>
            : <Stack spacing={1}>
                <Typography variant="body2" color="text.secondary">Generate shareable link</Typography>
                <Divider/>
                {attachmentAccessControls(
                    pendingIncludeRecordings,
                    pendingIncludeHar,
                    setPendingIncludeRecordings,
                    setPendingIncludeHar,
                )}
                {generationError && (
                    <Typography variant="caption" color="error">{generationError}</Typography>
                )}
            </Stack>;

    return <NoMaxWidthTooltip
        title={tooltipContent}
        arrow
        leaveDelay={400}
        slotProps={{
            tooltip: {
                sx: {
                    bgcolor: 'white',
                    color: 'text.primary',
                    boxShadow: 4,
                    borderRadius: 2,
                    p: 2,
                }
            },
            arrow: {sx: {color: 'white'}},
        }}
    >
        {isFetching ?
            <CircularProgress size={20} color="primary"/> :
            <Fab
                size="small"
                color={fabColor}
                onClick={shareLinkInfo ? copyShareLinkToClipboard : generateShareLink}
            >
                <Share/>
            </Fab>
        }
    </NoMaxWidthTooltip>
}
