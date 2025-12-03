import React from "react";
import "./variables.scss";
import "./global.scss";
import "./classes.scss";
import "./layout.scss";
import "./buttons.scss";
import favicon from "../static/favicon.ico"

export default () => (
	<div>
			<meta name="viewport" content="width=device-width, initial-scale=1"/>
			<meta charSet="utf-8"/>
			<link
				href={favicon}
				rel="icon"
				type="image/x-icon"
			/>
	</div>
)
