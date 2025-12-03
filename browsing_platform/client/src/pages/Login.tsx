import React from 'react';
import server from '../services/server';
import cookie from 'js-cookie';
import './login/Login.scss';
import withRouter, {IRouterProps} from "../services/withRouter";
import {CircularProgress, FormControl, IconButton, Input, InputLabel, Modal, Stack, Tooltip} from "@mui/material";
import {createTheme, ThemeProvider} from '@mui/material/styles';
import {LocalFlorist, Visibility, VisibilityOff} from "@mui/icons-material";

type IProps = {} & IRouterProps;

interface IState {
    redirect: string | null;
    email: string;
    password: string;
    showPassword: boolean;
    awaitingAuthentication: boolean;
    authenticationError: string | null;
}

const darkTheme = createTheme({
    palette: {
        mode: 'dark',
    },
});

class Login extends React.Component<IProps, IState> {
    constructor(props: IProps) {
        super(props);
        this.state = {
            redirect: props.searchParams.get("redirect"),
            email: props.searchParams.get("email") || "",
            password: "",
            showPassword: false,
            awaitingAuthentication: false,
            authenticationError: null,
        };
    }

    async componentDidMount() {
        this.props.setPageTitle(`Login`);
        const token = cookie.get('token');
        if (token && token.length) {
            server.get("permissions/", {ignoreErrors: true}).then((res) => {
                if (res.valid) {
                    this.proceedToSite();
                }
            });
        }
    }

    validateEmail = (email: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

    verifyPasswordLogin = async () => {
        if (this.state.awaitingAuthentication) return;
        const payload = {email: this.state.email, password: this.state.password};
        this.setState({awaitingAuthentication: true}, async () => {
            const res = await server.post("login/", payload);
            if (res.token) {
                this.setState({awaitingAuthentication: false});
                cookie.set('token', res.token, {expires: 30});
                this.proceedToSite();
            } else {
                const error = res?.error || `An Unknown Error Has Occurred`;
                this.setState({awaitingAuthentication: false, authenticationError: error});
            }
        });
    };

    proceedToSite = () => {
        if (this.state.redirect) {
            try {
                this.props.navigate(decodeURIComponent(this.state.redirect));
                return;
            } catch (e) {
                console.log(e);
            }
        }
        this.props.navigate("/search/")
    };

    renderEmailStage = () => (
        <Stack dir="column" alignItems="center" gap={2} sx={{width: "100%"}}>
            <h2>{`Login`}</h2>
            <FormControl
                variant="outlined"
                sx={{width: (window.innerWidth <= 768) ? "80%" : "500px"}}
            >
                <InputLabel>{`Email Address`}</InputLabel>
                <Input
                    value={this.state.email}
                    dir="ltr"
                    onChange={(e) => this.setState({email: e.target.value})}
                />
            </FormControl>
        </Stack>
    );

    renderPasswordForm = () => (
        <FormControl
            variant="outlined"
            sx={{width: (window.innerWidth <= 768) ? "80%" : "500px"}}
        >
            <InputLabel>{`Password`}</InputLabel>
            <Input
                type={this.state.showPassword ? "text" : "password"}
                value={this.state.password}
                onChange={(e) => this.setState({password: e.target.value})}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' && this.state.password.length) {
                        this.verifyPasswordLogin();
                    }
                }}
                endAdornment={
                    <Stack direction="row" alignItems="center" gap={0.5}>
                        <IconButton
                            size="small"
                            onClick={() => this.setState({showPassword: !this.state.showPassword})}
                            aria-label={`Toggle password visibility`}
                        >
                            {this.state.showPassword ? <VisibilityOff/> : <Visibility/>}
                        </IconButton>
                        {
                            this.state.awaitingAuthentication
                                ? <CircularProgress size={20}/>
                                : <Tooltip title={`Login`} placement="top" arrow disableInteractive>
                                    <IconButton
                                        color="success"
                                        size="small"
                                        disabled={!this.state.password.length}
                                        onClick={this.verifyPasswordLogin}
                                    >
                                        <LocalFlorist/>
                                    </IconButton>
                                </Tooltip>
                        }
                    </Stack>
                }
            />
        </FormControl>
    );

    render() {
        return <React.Fragment>
            <div className='page-wrap-login'>
                <ThemeProvider theme={darkTheme}>
                    <Stack dir="column" alignItems="center" gap={2}>
                        {
                            (window.innerWidth <= 768)
                                ?
                                <Stack className={"welcome-title-wrap"} direction="column" justifyContent="center">
                                    <h1 className={"welcome-title"}>Welcome to the Magrefa</h1>
                                    <Stack className={"welcome-title-wrap"} direction="row" justifyContent="center">
                                        <h1 className={"title-adornments"}>°𓏲🌿. 🍁⋆˚࿔</h1>
                                        <h1 className={"title-adornments"}>༄˖°.🍂.ೃ࿔*</h1>
                                    </Stack>
                                </Stack>
                                : <Stack className={"welcome-title-wrap"} justifyContent="center" direction="row"
                                         gap={2}>
                                    <h1 className={"title-adornments"}>°𓏲⋆🌿🍁⋆˚࿔</h1>
                                    <h1 className={"welcome-title"}>Welcome</h1>
                                    <h1 className={"title-adornments"}>༄˖°.🍂.ೃ࿔*</h1>
                                </Stack>
                        }
                        {this.renderEmailStage()}
                        {this.renderPasswordForm()}
                    </Stack>
                </ThemeProvider>
            </div>
            <Modal
                open={!!this.state.authenticationError}
                onClose={() => this.setState({authenticationError: null})}
                className={"modal-center"}
            >
                <div className={"authentication-modal"}>
                    <h2>Authentication Error</h2>
                    <p>{this.state.authenticationError}</p>
                </div>
            </Modal>
        </React.Fragment>
    }
}

export default withRouter(Login);