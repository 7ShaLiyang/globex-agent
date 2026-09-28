export interface Product {id:string;title:string;category:string;price:string;stock:number;icon:string;color:string;tags:string;description?:string;brand?:string;quantity?:number}
export interface Quote {subtotal:string;tax:string;shipping:string;total:string;currency:string;destination:string;notice:string}
export interface Order {id:string;status:string;items:Product[];quote:Quote;created_at:number}
export interface Proposal {id:string;kind:'order'|'preference'|'cancel_order';quote?:Quote;items?:Product[];key?:string;value?:string;order_id?:string;expires_at:number}
export interface Snapshot {cart:{items:Record<string,number>;products:Product[];revision:number};orders:Order[];preferences:{id:string;value:string}[];confirmations:Proposal[]}
export interface EventRow {seq:number;type:string;job?:string;data?:{text?:string;status?:string;error?:string;tool?:string;tool_call_name?:string;type?:string;agent?:string;result?:{products?:Product[];mode?:string};tasks?:{tasks?:{id:string;subject:string;status:string}[]}}}
export interface Session {id:string;title:string}
