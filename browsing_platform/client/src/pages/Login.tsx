import React, {useEffect, useState} from 'react';
import server from '../services/server';
import cookie from 'js-cookie';
import './login/Login.scss';
import {
    Alert,
    Box,
    Button,
    CircularProgress,
    FormControl,
    IconButton,
    Input,
    InputLabel,
    LinearProgress,
    Stack,
    Tooltip,
    Typography,
} from "@mui/material";
import {createTheme, ThemeProvider} from '@mui/material/styles';
import {ArrowBack, LocalFlorist, Visibility, VisibilityOff} from "@mui/icons-material";
import {useNavigate, useSearchParams} from "react-router";

const darkTheme = createTheme({palette: {mode: 'dark'}});

// zxcvbn is ~820KB minified — by far the heaviest dependency on this page. It's
// only needed for the password-strength meter in the change-password step, so
// load it on demand instead of baking it into the initial (eager) Login bundle.
type ZxcvbnFn = (password: string) => {score: number};
let zxcvbnPromise: Promise<ZxcvbnFn> | null = null;
const loadZxcvbn = (): Promise<ZxcvbnFn> =>
    (zxcvbnPromise ??= import('zxcvbn').then(m => ((m as any).default ?? m) as ZxcvbnFn));

type LoginStep = "password" | "verify_totp" | "change_password" | "setup_totp_qr";

const FORM_WIDTH = (window.innerWidth <= 768) ? "80%" : "500px";

const strengthColors = ["#d32f2f", "#f57c00", "#fbc02d", "#388e3c", "#1b5e20"];
const strengthLabels = ["Very weak", "Weak", "Fair", "Strong", "Very strong"];

export default function Login() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const [email, setEmail] = useState(searchParams.get("email") || "");
    const [password, setPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [busy, setBusy] = useState(false);
    const [errorMsg, setErrorMsg] = useState<string | null>(null);

    // Multi-step state
    const [step, setStep] = useState<LoginStep>("password");
    const [preAuthToken, setPreAuthToken] = useState("");
    const [totpCode, setTotpCode] = useState("");

    // Change-password step
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [showNewPassword, setShowNewPassword] = useState(false);
    const [passwordStrength, setPasswordStrength] = useState<{score: number} | null>(null);

    // Compute strength asynchronously once zxcvbn has loaded. While it's loading
    // passwordStrength stays null, which keeps the submit button disabled (see
    // the `!passwordStrength` guard below) — so a too-weak password can't slip
    // through during the brief first-load window.
    useEffect(() => {
        if (!newPassword) {
            setPasswordStrength(null);
            return;
        }
        let cancelled = false;
        loadZxcvbn().then(zxcvbn => {
            if (!cancelled) setPasswordStrength(zxcvbn(newPassword));
        });
        return () => {
            cancelled = true;
        };
    }, [newPassword]);

    // Setup TOTP step
    const [qrCode, setQrCode] = useState("");
    const [totpSecret, setTotpSecret] = useState("");

    const redirect = searchParams.get("redirect");

    useEffect(() => {
        document.title = `Login | Browsing Platform`;
        const token = cookie.get('token');
        if (token) {
            server.get("permissions/", {ignoreErrors: true}).then((res) => {
                if (res?.valid) proceedToSite();
            }).catch(() => {});
        }
    }, []);

    const storeTokenAndProceed = (token: string) => {
        cookie.set('token', token, {
            expires: 30,
            sameSite: 'strict',
            secure: window.location.protocol === 'https:',
        });
        proceedToSite();
    };

    const proceedToSite = () => {
        if (redirect) {
            try {
                const decoded = decodeURIComponent(redirect);
                if (decoded.startsWith('/') && !decoded.startsWith('//')) {
                    navigate(decoded);
                    return;
                }
            } catch (e) {}
        }
        navigate("/search/");
    };

    // Step 1: password
    const submitPassword = async () => {
        if (busy) return;
        setBusy(true);
        setErrorMsg(null);
        try {
            const res = await server.post("login/", {email, password}, undefined, {ignoreErrors: true});
            const next = res?.next_step;
            const pat = res?.pre_auth_token;
            if (!next || !pat) {
                setErrorMsg(res?.detail || res?.error || 'An unknown error occurred');
                return;
            }
            setPreAuthToken(pat);
            if (next === "change_password") {
                setStep("change_password");
            } else if (next === "setup_totp") {
                await loadTotpSetup(pat);
            } else if (next === "verify_totp") {
                setStep("verify_totp");
            }
        } catch (e: any) {
            setErrorMsg(e?.message || 'An unknown error occurred');
        } finally {
            setBusy(false);
        }
    };

    // Step: forced password change
    const submitChangePassword = async () => {
        if (busy) return;
        if (passwordStrength && passwordStrength.score < 3) {
            setErrorMsg("Password is too weak. Please choose a stronger password.");
            return;
        }
        setBusy(true);
        setErrorMsg(null);
        try {
            const res = await server.post("user/change-password/preauth", {
                pre_auth_token: preAuthToken,
                new_password: newPassword,
            }, undefined, {ignoreErrors: true});
            if (res?.token) {
                storeTokenAndProceed(res.token);
                return;
            }
            if (res?.next_step === "setup_totp" && res?.pre_auth_token) {
                await loadTotpSetup(res.pre_auth_token);
            } else {
                setErrorMsg(res?.detail || res?.error || 'An unknown error occurred');
            }
        } catch (e: any) {
            setErrorMsg(e?.message || 'An unknown error occurred');
        } finally {
            setBusy(false);
        }
    };

    // Load QR code for TOTP setup
    const loadTotpSetup = async (pat: string) => {
        setBusy(true);
        setErrorMsg(null);
        try {
            const res = await server.post("2fa/setup", {pre_auth_token: pat}, undefined, {ignoreErrors: true});
            if (res?.qr_code) {
                setQrCode(res.qr_code);
                setTotpSecret(res.secret);
                setPreAuthToken(res.pre_auth_token);
                setTotpCode("");
                setStep("setup_totp_qr");
            } else {
                setErrorMsg(res?.detail || res?.error || 'Failed to start 2FA setup');
            }
        } catch (e: any) {
            setErrorMsg(e?.message || 'An unknown error occurred');
        } finally {
            setBusy(false);
        }
    };

    // Step: verify TOTP code (normal login)
    const submitVerifyTotp = async () => {
        if (busy) return;
        setBusy(true);
        setErrorMsg(null);
        try {
            const res = await server.post("login/verify-2fa", {
                pre_auth_token: preAuthToken,
                totp_code: totpCode.trim(),
            }, undefined, {ignoreErrors: true});
            if (res?.token) {
                storeTokenAndProceed(res.token);
            } else {
                setErrorMsg(res?.detail || res?.error || 'Invalid code');
            }
        } catch (e: any) {
            setErrorMsg(e?.message || 'Invalid code');
        } finally {
            setBusy(false);
        }
    };

    const submitEnableTotp = async () => {
        if (busy) return;
        setBusy(true);
        setErrorMsg(null);
        try {
            const res = await server.post("2fa/enable", {
                pre_auth_token: preAuthToken,
                totp_code: totpCode.trim(),
            }, undefined, {ignoreErrors: true});
            if (res?.token) {
                storeTokenAndProceed(res.token);
            } else {
                setErrorMsg(res?.detail || res?.error || 'Invalid verification code');
            }
        } catch (e: any) {
            setErrorMsg(e?.message || 'Invalid verification code');
        } finally {
            setBusy(false);
        }
    };

    const renderPasswordStep = () => (
        <Stack alignItems="center" gap={2} sx={{width: "100%"}}>
            <h2>Login</h2>
            <FormControl variant="outlined" sx={{width: FORM_WIDTH}}>
                <InputLabel>Email Address</InputLabel>
                <Input
                    value={email}
                    dir="ltr"
                    onChange={(e) => setEmail(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && password.length) submitPassword(); }}
                />
            </FormControl>
            <FormControl variant="outlined" sx={{width: FORM_WIDTH}}>
                <InputLabel>Password</InputLabel>
                <Input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && password.length) submitPassword(); }}
                    endAdornment={
                        <Stack direction="row" alignItems="center" gap={0.5}>
                            <IconButton size="small" onClick={() => setShowPassword(p => !p)}>
                                {showPassword ? <VisibilityOff/> : <Visibility/>}
                            </IconButton>
                            {busy
                                ? <CircularProgress size={20}/>
                                : <Tooltip title="Login" placement="top" arrow disableInteractive>
                                    <IconButton
                                        color="success" size="small"
                                        disabled={!password.length || !email.length}
                                        onClick={submitPassword}
                                    >
                                        <LocalFlorist/>
                                    </IconButton>
                                </Tooltip>
                            }
                        </Stack>
                    }
                />
            </FormControl>
        </Stack>
    );

    const renderVerifyTotpStep = () => (
        <Stack alignItems="center" gap={2} sx={{width: "100%"}}>
            <Stack direction="row" alignItems="center" gap={1} sx={{width: FORM_WIDTH}}>
                <IconButton size="small" onClick={() => { setStep("password"); setTotpCode(""); }}>
                    <ArrowBack fontSize="small"/>
                </IconButton>
                <h2 style={{margin: 0}}>Two-Factor Authentication</h2>
            </Stack>
            <Typography sx={{width: FORM_WIDTH, color: "rgba(255,255,255,0.7)", fontSize: "0.9em"}}>
                Enter the 6-digit code from your authenticator app, or one of your 8-character backup codes.
            </Typography>
            <FormControl variant="outlined" sx={{width: FORM_WIDTH}}>
                <InputLabel>Verification Code</InputLabel>
                <Input
                    value={totpCode}
                    dir="ltr"
                    inputProps={{inputMode: "numeric", maxLength: 8}}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\s/g, ""))}
                    onKeyDown={(e) => { if (e.key === 'Enter' && totpCode.length >= 6) submitVerifyTotp(); }}
                    endAdornment={
                        busy
                            ? <CircularProgress size={20}/>
                            : <Tooltip title="Verify" placement="top" arrow disableInteractive>
                                <IconButton
                                    color="success" size="small"
                                    disabled={totpCode.length < 6}
                                    onClick={submitVerifyTotp}
                                >
                                    <LocalFlorist/>
                                </IconButton>
                            </Tooltip>
                    }
                />
            </FormControl>
        </Stack>
    );

    const renderChangePasswordStep = () => (
        <Stack alignItems="center" gap={2} sx={{width: "100%"}}>
            <h2>Set Your Password</h2>
            <Typography sx={{width: FORM_WIDTH, color: "rgba(255,255,255,0.7)", fontSize: "0.9em"}}>
                You need to set a new permanent password before continuing.
                Minimum 14 characters with uppercase, lowercase, digits, and a special character.
            </Typography>
            <FormControl variant="outlined" sx={{width: FORM_WIDTH}}>
                <InputLabel>New Password</InputLabel>
                <Input
                    type={showNewPassword ? "text" : "password"}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    endAdornment={
                        <IconButton size="small" onClick={() => setShowNewPassword(p => !p)}>
                            {showNewPassword ? <VisibilityOff/> : <Visibility/>}
                        </IconButton>
                    }
                />
            </FormControl>
            {newPassword.length > 0 && passwordStrength && (
                <Box sx={{width: FORM_WIDTH}}>
                    <LinearProgress
                        variant="determinate"
                        value={(passwordStrength.score / 4) * 100}
                        sx={{
                            height: 6,
                            borderRadius: 3,
                            backgroundColor: "rgba(255,255,255,0.15)",
                            "& .MuiLinearProgress-bar": {
                                backgroundColor: strengthColors[passwordStrength.score],
                            }
                        }}
                    />
                    <Typography sx={{fontSize: "0.8em", color: strengthColors[passwordStrength.score], mt: 0.5}}>
                        {strengthLabels[passwordStrength.score]}
                    </Typography>
                </Box>
            )}
            <FormControl variant="outlined" sx={{width: FORM_WIDTH}}>
                <InputLabel>Confirm New Password</InputLabel>
                <Input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') submitChangePassword(); }}
                    onPaste={(e) => e.preventDefault()}
                />
                {confirmPassword.length > 0 && newPassword !== confirmPassword && (
                    <Typography sx={{fontSize: "0.8em", color: "error.main", mt: 0.5}}>
                        Passwords do not match
                    </Typography>
                )}
            </FormControl>
            <Box sx={{width: FORM_WIDTH}}>
                {busy
                    ? <CircularProgress size={24}/>
                    : <Button
                        variant="contained"
                        color="success"
                        disabled={
                            newPassword.length < 14
                            || !passwordStrength
                            || passwordStrength.score < 3
                            || newPassword !== confirmPassword
                        }
                        onClick={submitChangePassword}
                    >
                        Set Password & Continue
                    </Button>
                }
            </Box>
        </Stack>
    );

    const renderSetupTotpQrStep = () => (
        <Stack alignItems="center" gap={2} sx={{width: "100%"}}>
            <h2>Set Up Two-Factor Authentication</h2>
            <Typography sx={{width: FORM_WIDTH, color: "rgba(255,255,255,0.7)", fontSize: "0.9em"}}>
                2FA is required. Scan the QR code with your authenticator app (Google Authenticator, Authy, etc.),
                then enter the 6-digit code it shows to confirm.
            </Typography>
            {qrCode && (
                <Box sx={{background: "white", padding: "12px", borderRadius: "8px", display: "inline-block"}}>
                    <img src={`data:image/png;base64,${qrCode}`} alt="TOTP QR Code" style={{width: 200, height: 200, display: "block"}}/>
                </Box>
            )}
            {totpSecret && (
                <Typography sx={{
                    width: FORM_WIDTH, fontSize: "0.75em", color: "rgba(255,255,255,0.5)",
                    wordBreak: "break-all", textAlign: "center"
                }}>
                    Manual entry: <strong style={{color: "rgba(255,255,255,0.8)"}}>{totpSecret}</strong>
                </Typography>
            )}
            <FormControl variant="outlined" sx={{width: FORM_WIDTH}}>
                <InputLabel>6-Digit Verification Code</InputLabel>
                <Input
                    value={totpCode}
                    dir="ltr"
                    inputProps={{inputMode: "numeric", maxLength: 6}}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                    onKeyDown={(e) => { if (e.key === 'Enter' && totpCode.length === 6) submitEnableTotp(); }}
                    endAdornment={
                        busy
                            ? <CircularProgress size={20}/>
                            : <Tooltip title="Verify & Activate" placement="top" arrow disableInteractive>
                                <IconButton
                                    color="success" size="small"
                                    disabled={totpCode.length !== 6}
                                    onClick={submitEnableTotp}
                                >
                                    <LocalFlorist/>
                                </IconButton>
                            </Tooltip>
                    }
                />
            </FormControl>
        </Stack>
    );

    return <React.Fragment>
        <div className='page-wrap-login'>
            <ThemeProvider theme={darkTheme}>
                <Stack dir="column" alignItems="center" gap={2}>
                    {(window.innerWidth <= 768)
                        ? <Stack className={"welcome-title-wrap"} direction="column" justifyContent="center">
                            <h1 className={"welcome-title"}>Welcome</h1>
                            <Stack className={"welcome-title-wrap"} direction="row" justifyContent="center">
                                <h1 className={"title-adornments"}>°𓏲🌿. 🍁⋆˚࿔</h1>
                                <h1 className={"title-adornments"}>༄˖°.🍂.ೃ࿔*</h1>
                            </Stack>
                        </Stack>
                        : <Stack className={"welcome-title-wrap"} justifyContent="center" direction="row" gap={2}>
                            <h1 className={"title-adornments"}>°𓏲⋆🌿🍁⋆˚࿔</h1>
                            <h1 className={"welcome-title"}>Welcome</h1>
                            <h1 className={"title-adornments"}>༄˖°.🍂.ೃ࿔*</h1>
                        </Stack>
                    }
                    {errorMsg && (
                        <Box sx={{width: FORM_WIDTH}}>
                            <Alert severity="error" onClose={() => setErrorMsg(null)}>{errorMsg}</Alert>
                        </Box>
                    )}
                    {step === "password" && renderPasswordStep()}
                    {step === "verify_totp" && renderVerifyTotpStep()}
                    {step === "change_password" && renderChangePasswordStep()}
                    {step === "setup_totp_qr" && renderSetupTotpQrStep()}
                </Stack>
            </ThemeProvider>
        </div>
    </React.Fragment>;
}
