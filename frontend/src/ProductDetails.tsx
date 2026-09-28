import {Plus,X} from 'lucide-react';
import type {Product} from './types';

type Props={product:Product;onClose:()=>void;onAdd:()=>void};

export default function ProductDetails({product,onClose,onAdd}:Props){
 return <div className="modal-backdrop" onClick={onClose}>
  <div className="modal product-modal" role="dialog" aria-modal="true" aria-label={product.title} onClick={e=>e.stopPropagation()}>
   <button className="modal-close" aria-label="关闭商品详情" onClick={onClose}><X/></button>
   <div className={'product-art '+product.color}><span>{product.icon}</span><small>{product.category.toUpperCase()}</small></div>
   <span className="mini-label">PRODUCT DETAILS</span>
   <h2>{product.title}</h2>
   <p className="product-description">{product.description||'暂无商品简介。'}</p>
   <div className="product-facts"><span>价格</span><b>${product.price}</b><span>库存</span><b>{product.stock}</b><span>商品编号</span><b>{product.id}</b></div>
   <p className="product-tags">{product.tags}</p>
   <button className="primary product-add" disabled={product.stock===0} onClick={onAdd}><Plus size={17}/>加入购物车</button>
  </div>
 </div>;
}
